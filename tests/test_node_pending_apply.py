"""Ручное сохранение занятой ноды и применение последних настроек."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import BackgroundTasks

from app.models.node import NodeStatus
from app.utils.usage_runtime import StaleObservationError, UsageState
from app.xray.node_operations import NodeOperationScheduler, OperationKind
from tests.test_node_operation_routes import load_route
from tests.test_node_operations import Executor


def test_edit_busy_node_saves_without_network(monkeypatch):
    """SOFT не запрещает PUT: новые параметры сохранены, RPC отложены."""
    route, operations = load_route(monkeypatch)
    state = UsageState()
    monkeypatch.setattr(route.node_lifecycle, "usage_state", state)
    monkeypatch.setattr(operations, "usage_state", state, raising=False)
    executor = Executor()
    scheduler = NodeOperationScheduler(executor, Mock(), lambda: {}, concurrency=1)
    monkeypatch.setattr(operations, "get_node_scheduler", lambda: scheduler)
    remove = Mock()
    monkeypatch.setattr(operations, "remove_node", remove)
    node = SimpleNamespace(id=7, name="new", status=NodeStatus.connecting)
    route.crud.update_node.return_value = node

    def execute(*_args):
        result = route.modify_node(SimpleNamespace(), BackgroundTasks(), node, Mock(), Mock())
        assert result.name == "new"
        remove.assert_not_called()

    scheduler.execute = execute
    active = scheduler.request(7, OperationKind.SOFT)
    executor.run()
    active.result()
    route.crud.update_node.assert_called_once()
    assert scheduler.snapshot()["active"] + scheduler.snapshot()["pending"] == 1


def test_edit_during_usage_waits_for_both_leases(monkeypatch):
    """Сохранение допустимо, но transport ждёт завершения обоих SQL-потребителей."""
    route, operations = load_route(monkeypatch)
    state = UsageState()
    old = state.observe_nodes({7: "old"})[7]
    user_release = state.acquire_collection(7, old)
    node_release = state.acquire_collection(7, old)
    monkeypatch.setattr(route.node_lifecycle, "usage_state", state)
    monkeypatch.setattr(operations, "usage_state", state, raising=False)
    executor = Executor()
    scheduler = NodeOperationScheduler(executor, Mock(), lambda: {}, concurrency=1)
    monkeypatch.setattr(operations, "get_node_scheduler", lambda: scheduler)
    monkeypatch.setattr(operations, "remove_node", Mock())
    node = SimpleNamespace(id=7, name="new", status=NodeStatus.connecting)
    route.crud.update_node.return_value = node

    route.modify_node(SimpleNamespace(), BackgroundTasks(), node, Mock(), Mock())
    assert not executor.jobs
    with pytest.raises(StaleObservationError):
        state.acquire_collection(7, old)
    user_release()
    assert not executor.jobs
    node_release()
    assert len(executor.jobs) == 1
    route.crud.update_node.assert_called_once()


def test_failed_edit_preserves_running_operation(monkeypatch):
    """Ошибка БД не отменяет прежнюю команду и не закрывает сбор навсегда."""
    route, operations = load_route(monkeypatch)
    state = UsageState()
    state.observe_nodes({7: "old"})
    monkeypatch.setattr(route.node_lifecycle, "usage_state", state)
    monkeypatch.setattr(operations, "usage_state", state, raising=False)
    executor = Executor()
    scheduler = NodeOperationScheduler(executor, Mock(), lambda: {}, concurrency=1)
    monkeypatch.setattr(operations, "get_node_scheduler", lambda: scheduler)
    route.crud.update_node.side_effect = RuntimeError("database")

    def execute(*_args):
        with pytest.raises(RuntimeError, match="database"):
            route.modify_node(SimpleNamespace(), BackgroundTasks(), SimpleNamespace(id=7), Mock(), Mock())
        assert scheduler.is_current(7)

    scheduler.execute = execute
    active = scheduler.request(7, OperationKind.SOFT)
    executor.run()
    active.result()
    token = state.observe_nodes({7: "old"})[7]
    state.acquire_collection(7, token)()


def test_pending_flag_commits_with_settings(tmp_path):
    """Параметры и необходимость HARD восстанавливаются из реальной БД."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.db import crud
    from app.db.base import Base
    from app.db.models import Node
    from app.models.node import NodeModify

    engine = create_engine(f"sqlite:///{tmp_path / 'pending.db'}")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            db.add(Node(id=7, name="old", address="127.0.0.1", port=62050, api_port=62051))
            db.commit()
            assert db.get(Node, 7).config_apply_pending is False
            crud.update_node(db, db.get(Node, 7), NodeModify(name="new"))
        with Session(engine) as db:
            node = db.get(Node, 7)
            assert (node.name, node.config_apply_pending) == ("new", True)
    finally:
        engine.dispose()


def test_apply_coalesces_and_supersedes_running_operation():
    """Повторные save не строят config и не добавляют задания поверх активного."""
    executor = Executor()
    factory = Mock(return_value={})
    scheduler = NodeOperationScheduler(executor, Mock(), factory, concurrency=1)
    seen = []

    def execute(node, kind, _factory):
        seen.append(kind)
        if kind == OperationKind.SOFT:
            for _ in range(30):
                with scheduler.edit(node):
                    pass
                scheduler.ready(node)
            assert not scheduler.is_current(node)
            assert len(executor.jobs) == 0

    scheduler.execute = execute
    scheduler.request(7, OperationKind.SOFT)
    scheduler.request(8, OperationKind.SOFT)
    executor.run()
    assert scheduler.snapshot()["active"] == 1
    executor.run()
    assert seen == [OperationKind.SOFT, OperationKind.APPLY]
    factory.assert_not_called()
    executor.run()


def test_apply_rebuilds_transport_and_acknowledges_only_current(monkeypatch):
    """Повторный save во время HARD не даёт старому успеху снять pending."""
    route, operations = load_route(monkeypatch)
    from unittest.mock import MagicMock

    state = UsageState()
    monkeypatch.setattr(operations, "usage_state", state, raising=False)
    executor = Executor()
    scheduler = NodeOperationScheduler(executor, operations._execute_node_operation, lambda: {}, concurrency=1)
    monkeypatch.setattr(operations, "get_node_scheduler", lambda: scheduler)
    db = MagicMock()
    get_db = MagicMock()
    get_db.return_value.__enter__.return_value = db
    monkeypatch.setattr(operations, "GetDB", get_db)
    node = SimpleNamespace(
        id=7, name="new", status=NodeStatus.connecting, config_apply_pending=True, control_session_id=None, inbounds=[]
    )
    monkeypatch.setattr(operations, "crud", Mock(get_node_by_id=Mock(return_value=node)))
    monkeypatch.setattr(operations, "_cascade_kwargs", lambda *_: {"role": "direct"})
    monkeypatch.setattr(operations, "_blocked_user_ids", lambda *_: set())
    monkeypatch.setattr(operations, "node_config_json", lambda *_: "fresh-config")
    monkeypatch.setattr(operations, "XRAY_NODE_CONNECT_RETRIES", 1)
    created = []

    def add(_node):
        transport = Mock()
        transport._session_id = None
        transport.get_version.return_value = "26.10"
        created.append(transport)
        operations.xray.nodes[7] = transport
        return transport

    monkeypatch.setattr(operations, "add_node", add)
    remove = Mock(side_effect=lambda *_args, **_kw: operations.xray.nodes.pop(7, None))
    monkeypatch.setattr(operations, "remove_node", remove)
    first = operations.apply_node(7)
    add_mock = add

    def edited_during_start(_node):
        transport = add_mock(_node)
        if len(created) == 1:

            def restart(**_kwargs):
                with scheduler.edit(7):
                    node.name = "latest"
                    node.config_apply_pending = True
                operations.apply_node(7)

            transport.restart.side_effect = restart
        return transport

    monkeypatch.setattr(operations, "add_node", edited_during_start)
    executor.run()
    assert first.done() and node.config_apply_pending is True
    executor.run()
    assert node.config_apply_pending is False
    assert len(created) == 2 and remove.call_count == 2
    created[1].connect.assert_called_once()
    created[1].restart.assert_called_once_with(config_json="fresh-config")


def test_usage_idle_callback_is_single_and_runs_outside_mutex():
    """Повторные правки не копят callbacks; уведомление не держит usage lock."""
    state = UsageState()
    epoch = state.observe_nodes({7: "old"})[7]
    release = state.acquire_collection(7, epoch)
    with state.edit(7):
        pass
    called = []
    for number in range(30):
        state.when_idle(7, lambda n=number: called.append((n, state.snapshot())))
    assert len(state._idle_callbacks) == 1
    release()
    assert [item[0] for item in called] == [29]
    assert not state._idle_callbacks


def test_migration_adds_default_to_existing_rows_and_downgrades():
    """Реальный Alembic upgrade заполняет false старым нодам; downgrade обратим."""
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, text

    path = next(
        (Path(__file__).parents[1] / "app/db/migrations/versions").glob("*npvpn_2108_pending_manual_node_apply.py")
    )
    spec = importlib.util.spec_from_file_location("pending_apply_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE nodes (id INTEGER PRIMARY KEY, name VARCHAR(256))"))
        conn.execute(text("INSERT INTO nodes VALUES (7, 'old')"))
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
            assert conn.execute(text("SELECT config_apply_pending FROM nodes")).scalar_one() == 0
            migration.downgrade()
        assert conn.execute(text("SELECT name FROM nodes")).scalar_one() == "old"
    engine.dispose()


def test_new_response_does_not_expose_internal_apply_flag():
    """Публичный контракт ноды не раскрывает внутренний флаг оркестрации."""
    from app.models.node import NodeResponse

    assert "config_apply_pending" not in NodeResponse.model_fields


def test_collection_pause_rolls_back_if_database_save_fails():
    """Ошибка сохранения не делает старые метаданные недоступными для reset."""
    state = UsageState()
    epoch = state.observe_nodes({7: "old"})[7]
    with pytest.raises(RuntimeError):
        with state.edit(7):
            raise RuntimeError("database")
    state.acquire_collection(7, epoch)()


def test_submit_failure_keeps_durable_pending_and_can_retry(monkeypatch):
    """Отказ executor не теряет необходимость применения и не копит очередь."""
    route, operations = load_route(monkeypatch)
    state = UsageState()
    executor = Executor()
    scheduler = NodeOperationScheduler(executor, Mock(), lambda: {}, concurrency=1)
    monkeypatch.setattr(operations, "get_node_scheduler", lambda: scheduler)
    executor.submit = Mock(side_effect=RuntimeError("submit failed"))
    failed = operations.apply_node(7, accounting=state)
    with pytest.raises(RuntimeError, match="submit failed"):
        failed.result()
    assert scheduler.snapshot()["active"] == scheduler.snapshot()["pending"] == 0
    executor.submit = Executor.submit.__get__(executor)
    retried = operations.apply_node(7, accounting=state)
    assert len(executor.jobs) == 1 and retried is not failed


def test_enabled_query_includes_only_pending_disabled():
    """Health видит незавершённое отключение, но не обычные Disabled-ноды."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.db import crud
    from app.db.base import Base
    from app.db.models import Node

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            for number, status, pending in [
                (1, NodeStatus.connected, False),
                (2, NodeStatus.disabled, True),
                (3, NodeStatus.disabled, False),
            ]:
                db.add(
                    Node(
                        id=number,
                        name=str(number),
                        address="127.0.0.1",
                        port=62050,
                        api_port=62051,
                        status=status,
                        config_apply_pending=pending,
                    )
                )
            db.commit()
            assert {row.id for row in crud.get_nodes(db, enabled=True)} == {1}
            assert {row.id for row in crud.get_nodes(db, enabled=True, include_pending=True)} == {1, 2}
    finally:
        engine.dispose()


def test_superseded_operation_cannot_send_next_rest_request():
    """Проверка внутри REST transport не превращается в сетевую ошибку/повтор."""
    from app.xray.node_operations import NodeOperationSuperseded
    from tests.test_node_soft_reconnect import _make_node

    node = _make_node()
    executor = Executor()
    scheduler = NodeOperationScheduler(executor, Mock(), lambda: {}, concurrency=1)
    node._operation_check = lambda: scheduler.check_current(7)

    def execute(*_args):
        with scheduler.edit(7):
            pass
        with pytest.raises(NodeOperationSuperseded):
            node.make_request("/restart", timeout=90, config="old")

    scheduler.execute = execute
    future = scheduler.request(7, OperationKind.SOFT)
    executor.run()
    future.result()
    node.session.post.assert_not_called()


def test_old_status_is_not_published_after_edit(monkeypatch):
    """Проверка актуальности и SQL публикация упорядочены с save."""
    route, operations = load_route(monkeypatch)
    db = Mock()
    monkeypatch.setattr(operations, "GetDB", db)
    executor = Executor()
    scheduler = NodeOperationScheduler(executor, Mock(), lambda: {}, concurrency=1)
    monkeypatch.setattr(operations, "get_node_scheduler", lambda: scheduler)

    def execute(*_args):
        with scheduler.edit(7):
            pass
        assert operations._change_node_status(7, NodeStatus.connected) is False

    scheduler.execute = execute
    scheduler.request(7, OperationKind.SOFT)
    executor.run()
    db.assert_not_called()


def test_edit_does_not_wait_for_another_nodes_sql():
    """Metadata-секция локальна ноде, общий scheduler lock не занят SQL."""
    import threading

    executor = Executor()
    scheduler = NodeOperationScheduler(executor, Mock(), lambda: {}, concurrency=1)
    entered, done = threading.Event(), threading.Event()

    def other_node():
        with scheduler.edit(8):
            entered.set()
        done.set()

    with scheduler.metadata(7):
        thread = threading.Thread(target=other_node)
        thread.start()
        assert entered.wait(3) and done.wait(3)
    thread.join(3)
    assert not thread.is_alive()


@pytest.mark.parametrize("fails", [False, True])
def test_pending_disable_after_restart_stops_remote_and_preserves_failure(monkeypatch, fails):
    """Пустой локальный registry не означает, что удалённый Xray уже выключен."""
    from unittest.mock import MagicMock

    route, operations = load_route(monkeypatch)
    state = UsageState()
    monkeypatch.setattr(operations, "usage_state", state)
    executor = Executor()
    scheduler = NodeOperationScheduler(executor, operations._execute_node_operation, lambda: {}, concurrency=1)
    monkeypatch.setattr(operations, "get_node_scheduler", lambda: scheduler)
    node = SimpleNamespace(
        id=7, status=NodeStatus.disabled, config_apply_pending=True, control_session_id="saved-session", message=None
    )
    crud = Mock(get_node_by_id=Mock(return_value=node))
    monkeypatch.setattr(operations, "crud", crud)
    db = MagicMock()
    monkeypatch.setattr(operations, "GetDB", Mock(return_value=db))
    transport = Mock()
    transport.stop.side_effect = RuntimeError("offline") if fails else None

    def add(_node):
        operations.xray.nodes[7] = transport
        return transport

    monkeypatch.setattr(operations, "add_node", add)

    def disconnected(*_args, **_kwargs):
        operations.xray.nodes.pop(7, None)
        node.control_session_id = None

    remove = Mock(side_effect=disconnected)
    monkeypatch.setattr(operations, "remove_node", remove)
    future = operations.apply_node(7)
    executor.run()
    if fails:
        with pytest.raises(RuntimeError, match="offline"):
            future.result()
        assert node.config_apply_pending is True and node.message == "offline"
    else:
        assert future.result() is True
        assert node.config_apply_pending is False and node.control_session_id is None
        remove.assert_called_once()
    transport.adopt_control_session.assert_called_once_with("saved-session")
    transport.stop.assert_called_once()
    transport.start.assert_not_called()
    transport.restart.assert_not_called()


def test_delete_admission_is_serialized_with_metadata_save():
    """Delete не входит в DB-фазу одновременно с незавершённым edit commit."""
    import threading

    scheduler = NodeOperationScheduler(Executor(), Mock(), lambda: {}, concurrency=1)
    entered = threading.Event()

    def deleting():
        with scheduler.mutation(7):
            entered.set()

    with scheduler.edit(7):
        thread = threading.Thread(target=deleting)
        thread.start()
        entered_while_saving = entered.wait(0.1)
    thread.join(3)
    assert not thread.is_alive() and entered.is_set()
    assert not entered_while_saving


def test_stale_orm_pending_true_is_written_again_after_old_ack(tmp_path):
    """Предзагруженный PUT обязан записать True после конкурирующего ack=False."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.db import crud
    from app.db.base import Base
    from app.db.models import Node
    from app.models.node import NodeModify

    engine = create_engine(f"sqlite:///{tmp_path / 'stale.db'}")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            db.add(
                Node(
                    id=7,
                    name="old",
                    address="127.0.0.1",
                    port=62050,
                    api_port=62051,
                    status=NodeStatus.connecting,
                    config_apply_pending=True,
                )
            )
            db.commit()
        with Session(engine) as request, Session(engine) as worker:
            stale = request.get(Node, 7)
            previous = worker.get(Node, 7)
            previous.config_apply_pending = False
            previous.status = NodeStatus.connected
            worker.commit()
            crud.update_node(request, stale, NodeModify(name="latest"))
        with Session(engine) as db:
            saved = db.get(Node, 7)
            assert (saved.name, saved.config_apply_pending, saved.status) == ("latest", True, NodeStatus.connecting)
    finally:
        engine.dispose()


def test_new_inbound_and_failed_edit_do_not_partially_commit(tmp_path):
    """Новый inbound не фиксирует pending/настройки до ошибки последующего шага."""
    from sqlalchemy import create_engine, event
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session

    from app.db import crud
    from app.db.base import Base
    from app.db.models import Node, ProxyInbound
    from app.models.node import CascadeRouteModel, NodeModify

    engine = create_engine(f"sqlite:///{tmp_path / 'atomic.db'}")

    @event.listens_for(engine, "connect")
    def enforce_fks(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            db.add(Node(id=7, name="old", address="127.0.0.1", port=62050, api_port=62051))
            db.commit()
            with pytest.raises(IntegrityError):
                crud.update_node(
                    db,
                    db.get(Node, 7),
                    NodeModify(
                        name="partial",
                        inbounds=["new-inbound"],
                        cascade_routes=[
                            CascadeRouteModel(
                                exit_node_id=999, entry_inbound_tag="new-inbound", cascade_inbound_tag="new-cascade"
                            )
                        ],
                    ),
                )
            db.rollback()
        with Session(engine) as db:
            assert (db.get(Node, 7).name, db.get(Node, 7).config_apply_pending) == ("old", False)
            assert db.query(ProxyInbound).count() == 0
    finally:
        engine.dispose()


def test_stale_health_after_ack_does_not_pause_or_apply_again(monkeypatch):
    """Устаревший hint из health не приостанавливает учёт после успешного ack."""
    from unittest.mock import MagicMock

    route, operations = load_route(monkeypatch)
    executor = Executor()
    scheduler = NodeOperationScheduler(executor, Mock(), lambda: {}, concurrency=1)
    monkeypatch.setattr(operations, "get_node_scheduler", lambda: scheduler)
    state = UsageState()
    token = state.observe_nodes({7: "ready"})[7]
    db = MagicMock()
    monkeypatch.setattr(operations, "GetDB", Mock(return_value=db))
    monkeypatch.setattr(
        operations, "crud", Mock(get_node_by_id=Mock(return_value=SimpleNamespace(config_apply_pending=False)))
    )
    operations.apply_node(7, accounting=state, recover=True)
    state.acquire_collection(7, token)()
    assert not executor.jobs


def test_disabled_rest_stop_fetches_peer_certificate_before_ping(monkeypatch):
    from app.xray import node as module
    from tests.test_node_soft_reconnect import _make_node

    node = _make_node()
    node._node_cert = None
    node._node_certfile = None
    monkeypatch.setattr(module, "fetch_server_certificate", Mock(return_value="CERT"))
    monkeypatch.setattr(module, "string_to_temp_file", Mock(return_value=SimpleNamespace(name="peer.pem")))
    calls = []

    def request(path, **_kwargs):
        assert node.session.verify == "peer.pem", "TLS must use node's pinned cert"
        calls.append(path)
        return {}

    node.make_request = request
    node.stop()
    assert calls == ["/ping", "/stop"]


def test_edit_after_restart_response_skips_old_grpc_readiness(monkeypatch):
    from app.xray import node as module
    from app.xray.node_operations import NodeOperationSuperseded
    from tests.test_node_soft_reconnect import _make_node

    node = _make_node()
    executor = Executor()
    scheduler = NodeOperationScheduler(executor, Mock(), lambda: {}, concurrency=1)
    node._operation_check = lambda: scheduler.check_current(7)
    node._ensure_control_session = Mock()
    api = Mock()
    monkeypatch.setattr(module, "XRayAPI", api)
    monkeypatch.setattr(module.grpc, "channel_ready_future", Mock())

    def response(*_args, **_kwargs):
        with scheduler.edit(7):
            pass
        return Mock(status_code=200, json=Mock(return_value={}))

    node.session.post.side_effect = response

    def execute(*_args):
        with pytest.raises(NodeOperationSuperseded):
            node.restart(config_json="old")

    scheduler.execute = execute
    future = scheduler.request(7, OperationKind.HARD)
    executor.run()
    future.result()
    api.assert_not_called()


def test_rpyc_connect_does_not_retry_after_edit(monkeypatch):
    from app.xray import node as module
    from app.xray.node_operations import NodeOperationSuperseded

    legacy = module.RPyCXRayNode.__new__(module.RPyCXRayNode)
    legacy.address = "127.0.0.1"
    legacy.port = 62050
    legacy._keyfile = legacy._certfile = SimpleNamespace(name="cert")
    legacy._service = object()
    executor = Executor()
    scheduler = NodeOperationScheduler(executor, Mock(), lambda: {}, concurrency=1)
    legacy._operation_check = lambda: scheduler.check_current(7)
    monkeypatch.setattr(module, "fetch_server_certificate", Mock(return_value="CERT"))
    monkeypatch.setattr(module, "string_to_temp_file", Mock(return_value=SimpleNamespace(name="cert")))
    conn = Mock()

    def ping():
        with scheduler.edit(7):
            pass
        raise EOFError("old")

    conn.ping.side_effect = ping
    connect = Mock(return_value=conn)
    monkeypatch.setattr(module.rpyc, "ssl_connect", connect)

    def execute(*_args):
        with pytest.raises(NodeOperationSuperseded):
            legacy.connect()

    scheduler.execute = execute
    future = scheduler.request(7, OperationKind.HARD)
    executor.run()
    future.result()
    connect.assert_called_once()


@pytest.mark.parametrize("failed_save", [False, True])
def test_old_session_listener_after_edit_before_replacement(monkeypatch, failed_save):
    route, operations = load_route(monkeypatch)
    state = UsageState()
    monkeypatch.setattr(route.node_lifecycle, "usage_state", state)
    token = state.observe_nodes({7: "old"})[7]
    release = state.acquire_collection(7, token)
    scheduler = NodeOperationScheduler(Executor(), Mock(), lambda: {}, concurrency=1)
    monkeypatch.setattr(operations, "get_node_scheduler", lambda: scheduler)
    node = SimpleNamespace(
        id=7,
        name="old",
        status=NodeStatus.connecting,
        address="127.0.0.1",
        port=62050,
        api_port=62051,
        protocol="rest",
        usage_coefficient=1,
    )
    transport = Mock()
    monkeypatch.setattr(operations, "XRayNode", Mock(return_value=transport))
    monkeypatch.setattr(operations, "remove_node", Mock())
    monkeypatch.setattr(operations, "get_tls", lambda: {"key": "k", "certificate": "c"})
    persist = Mock()
    monkeypatch.setattr(operations, "_persist_control_session", persist)
    operations.add_node(node)
    listener = transport.set_control_session_listener.call_args.args[0]
    route.crud.update_node.return_value = node
    if failed_save:
        route.crud.update_node.side_effect = RuntimeError("database")
        with pytest.raises(RuntimeError):
            route.modify_node(SimpleNamespace(), BackgroundTasks(), node, Mock(), Mock())
    else:
        route.modify_node(SimpleNamespace(), BackgroundTasks(), node, Mock(), Mock())
    assert operations.xray.nodes[7] is transport
    listener("old-session")
    if failed_save:
        persist.assert_called_once_with(7, "old-session")
    else:
        persist.assert_not_called()
    release()


def test_saved_edit_wakes_old_retry_delay():
    import threading
    from concurrent.futures import ThreadPoolExecutor

    entered = threading.Event()
    woke = threading.Event()
    scheduler = None

    class Wake:
        def wait(self, _delay):
            entered.set()
            assert woke.wait(3), "edit did not interrupt retry delay"

        def set(self):
            woke.set()

    def execute(node, kind, _factory):
        if kind == OperationKind.HARD:
            scheduler._local.intent.wake = Wake()
            scheduler.wait_current(node, 60)
            raise AssertionError("old retry continued")
        return True

    with ThreadPoolExecutor(max_workers=1) as pool:
        scheduler = NodeOperationScheduler(pool, execute, lambda: {}, concurrency=1)
        old = scheduler.request(7, OperationKind.HARD)
        try:
            assert entered.wait(3)
            with scheduler.edit(7):
                pass
            latest = scheduler.prepare_apply(7)
            scheduler.ready(7)
            assert old.result(timeout=3) is False
            assert latest.result(timeout=3) is True
        finally:
            woke.set()


@pytest.mark.parametrize("disconnect_fails", [False, True])
def test_disabled_stop_keeps_session_if_remote_disconnect_fails(monkeypatch, disconnect_fails):
    """Подтверждённый stop не выдаётся за успешный remote disconnect сессии."""
    from unittest.mock import MagicMock

    from app.xray.node import NodeAPIError
    from tests.test_node_soft_reconnect import _make_node

    route, operations = load_route(monkeypatch)
    state = UsageState()
    monkeypatch.setattr(operations, "usage_state", state)
    executor = Executor()
    scheduler = NodeOperationScheduler(executor, operations._execute_node_operation, lambda: {}, concurrency=1)
    monkeypatch.setattr(operations, "get_node_scheduler", lambda: scheduler)
    row = SimpleNamespace(
        id=7, status=NodeStatus.disabled, config_apply_pending=True, control_session_id="saved-session", message=None
    )
    monkeypatch.setattr(operations, "GetDB", Mock(return_value=MagicMock()))
    monkeypatch.setattr(operations, "crud", Mock(get_node_by_id=Mock(return_value=row)))
    transport = _make_node()
    transport._session_id = "saved-session"

    def persist(session):
        row.control_session_id = session

    transport.set_control_session_listener(persist)

    def request(path, **_kwargs):
        if path == "/disconnect" and disconnect_fails:
            raise NodeAPIError(0, "unavailable")
        return {}

    transport.make_request = request
    operations.xray.nodes[7] = transport
    future = operations.apply_node(7)
    executor.run()
    assert future.result() is True
    expected_session = "saved-session" if disconnect_fails else None
    assert row.config_apply_pending is False and row.control_session_id == expected_session


def test_repeated_save_uses_latest_sql_settings_and_config(monkeypatch, tmp_path):
    """Следующий HARD берёт новый адрес/порты/inbounds из отдельной SQL-сессии."""
    import json
    from contextlib import contextmanager

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    route, operations = load_route(monkeypatch)
    from app.db import crud as real_crud
    from app.db.base import Base
    from app.db.models import Node
    from app.models.node import NodeModify

    engine = create_engine(f"sqlite:///{tmp_path / 'latest-apply.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Node(id=7, name="test", address="192.0.2.1", port=62050, api_port=62051))
        db.commit()
    monkeypatch.setattr(route.node_lifecycle, "crud", real_crud)
    state = UsageState()
    monkeypatch.setattr(route.node_lifecycle, "usage_state", state)
    monkeypatch.setattr(operations, "usage_state", state)
    executor = Executor()
    generation = [1]
    control = NodeOperationScheduler(
        executor, operations._execute_node_operation, lambda: {"generation": generation[0]}, concurrency=1
    )
    monkeypatch.setattr(operations, "get_node_scheduler", lambda: control)

    @contextmanager
    def get_db():
        with Session(engine) as db:
            yield db

    monkeypatch.setattr(operations, "GetDB", get_db)
    monkeypatch.setattr(operations, "get_tls", lambda: {"key": "k", "certificate": "c"})
    monkeypatch.setattr(operations, "_cascade_kwargs", lambda *_: {"role": "direct"})
    monkeypatch.setattr(operations, "_blocked_user_ids", lambda *_: set())
    monkeypatch.setattr(operations, "XRAY_NODE_CONNECT_RETRIES", 1)

    def config_json(config, tags, *_args):
        return json.dumps({**config, "inbounds": tags}, sort_keys=True)

    monkeypatch.setattr(operations, "node_config_json", config_json)
    transports = []

    def create(**_kwargs):
        transport = Mock()
        transport._session_id = None
        transport.get_version.return_value = "26.10.21"
        transports.append(transport)
        if len(transports) == 1:

            def second_save(**_args):
                generation[0] = 2
                with Session(engine) as db:
                    route.modify_node(
                        NodeModify(address="198.51.100.20", port=63050, api_port=63051, inbounds=["second"]),
                        BackgroundTasks(),
                        db.get(Node, 7),
                        db,
                        Mock(),
                    )

            transport.restart.side_effect = second_save
        return transport

    factory = Mock(side_effect=create)
    monkeypatch.setattr(operations, "XRayNode", factory)
    try:
        with Session(engine) as db:
            route.modify_node(
                NodeModify(address="192.0.2.10", inbounds=["first"]), BackgroundTasks(), db.get(Node, 7), db, Mock()
            )
        executor.run()
        with Session(engine) as db:
            assert db.get(Node, 7).config_apply_pending is True
        executor.run()
        first, latest = factory.call_args_list
        assert first.kwargs["address"] == "192.0.2.10"
        assert (latest.kwargs["address"], latest.kwargs["port"], latest.kwargs["api_port"]) == (
            "198.51.100.20",
            63050,
            63051,
        )
        assert json.loads(transports[0].restart.call_args.kwargs["config_json"]) == {
            "generation": 1,
            "inbounds": ["first"],
        }
        assert json.loads(transports[1].restart.call_args.kwargs["config_json"]) == {
            "generation": 2,
            "inbounds": ["second"],
        }
        with Session(engine) as db:
            assert db.get(Node, 7).config_apply_pending is False
    finally:
        engine.dispose()
