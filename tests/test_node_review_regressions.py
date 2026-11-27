"""Регрессии, подтверждённые при ревью NPVPN-2108."""

from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from app.models.node import NodeStatus
from app.utils.usage_runtime import UsageState, ready_apis
from app.xray.node_operations import NodeOperationScheduler, NodeOperationSuperseded, OperationKind
from tests.test_node_operation_routes import load_route
from tests.test_node_operations import Executor


def arrange(monkeypatch):
    route, ops = load_route(monkeypatch)
    state = UsageState()
    executor = Executor()
    scheduler = NodeOperationScheduler(executor, Mock(), lambda: {}, concurrency=1)
    monkeypatch.setattr(ops, "get_node_scheduler", lambda: scheduler)
    monkeypatch.setattr(ops, "usage_state", state)
    monkeypatch.setattr(route.node_lifecycle, "usage_state", state)
    return route.node_lifecycle, ops, state, executor, scheduler


def test_committed_edit_supersedes_even_when_response_refresh_fails(monkeypatch):
    lifecycle, ops, state, executor, scheduler = arrange(monkeypatch)
    db = Mock()
    db.refresh.side_effect = RuntimeError("refresh after commit")
    row = SimpleNamespace(id=7)

    def update(_db, _node, _modify, *, commit=True):
        if commit:
            _db.commit()
            _db.refresh(_node)
        return row

    lifecycle.crud.update_node.side_effect = update

    def execute(*_args):
        with pytest.raises(RuntimeError, match="refresh after commit"):
            lifecycle.modify_node(db, row, Mock(), Mock())
        assert not scheduler.is_current(7)
        assert scheduler.pending(7)
        assert state.observe_nodes({7: "new"}) == {}
        return True

    scheduler.execute = execute
    future = scheduler.request(7, OperationKind.APPLY)
    executor.run()
    assert future.result() is True
    db.commit.assert_called_once()


def test_stale_idle_callback_does_not_release_next_apply(monkeypatch):
    _, ops, state, executor, scheduler = arrange(monkeypatch)
    epoch = state.observe_nodes({7: "node"})[7]
    release = state.acquire_collection(7, epoch)
    ops.apply_node(7)
    stale = state._idle_callbacks.pop(7)
    release()
    scheduler.execute = lambda *_: state.resume(7)
    ops.apply_node(7)
    executor.run()
    epoch = state.observe_nodes({7: "node"})[7]
    release = state.acquire_collection(7, epoch)
    future = ops.apply_node(7)
    stale()
    assert not executor.jobs
    release()
    executor.run()
    assert future.done()


def test_failed_delete_recovers_pending_apply_and_preserves_pause(monkeypatch):
    lifecycle, ops, state, executor, scheduler = arrange(monkeypatch)
    scheduler.request(9, OperationKind.SOFT)
    row = SimpleNamespace(id=7, config_apply_pending=True)
    ops.apply_node(7)
    lifecycle.crud.remove_node.side_effect = RuntimeError("delete failed")
    monkeypatch.setattr(ops, "GetDB", Mock(return_value=MagicMock()))
    monkeypatch.setattr(ops, "crud", Mock(get_node_by_id=Mock(return_value=row)))
    with pytest.raises(RuntimeError, match="delete failed"):
        lifecycle.remove_node(Mock(), row)
    assert state.observe_nodes({7: "new"}) == {}
    assert scheduler.pending(7)


def test_observation_during_failed_edit_preserves_epoch_and_freshness():
    state = UsageState(clock=lambda: 123)
    epoch = state.observe_nodes({7: "old"})[7]
    state.mark_success(7, "user", epoch)
    before = state.snapshot()["nodes"]
    with pytest.raises(RuntimeError), state.edit(7):
        assert state.observe_nodes({7: "old"}) == {}
        raise RuntimeError("rollback")
    assert state.observe_nodes({7: "old"}) == {7: epoch}
    assert state.snapshot()["nodes"] == before
    state.acquire_collection(7, epoch)()


def test_superseded_transport_is_not_ready_for_accounting():
    node = SimpleNamespace(_started=True, _session_id="sid", _api=Mock(), _superseded=True)
    assert ready_apis({7: node}) == {}


@pytest.fixture
def node_database(monkeypatch, tmp_path):
    load_route(monkeypatch)
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.db import crud
    from app.db.base import Base
    from app.db.models import Node
    from app.models.node import NodeModify

    engine = create_engine(f"sqlite:///{tmp_path / 'endpoint.db'}")
    Base.metadata.create_all(engine)
    try:
        yield engine, Session, Node, NodeModify, crud
    finally:
        engine.dispose()


@pytest.mark.parametrize("status", [NodeStatus.disabled, NodeStatus.connecting])
@pytest.mark.parametrize("stop_fails", [False, True])
def test_previous_endpoint_survives_repeated_save_and_process_restart(monkeypatch, node_database, stop_fails, status):
    lifecycle, ops, state, executor, scheduler = arrange(monkeypatch)
    engine, Session, Node, NodeModify, real_crud = node_database
    with Session(engine) as db:
        row = Node(
            id=7,
            name="node",
            address="192.0.2.1",
            port=62050,
            api_port=62051,
            status=NodeStatus.connected,
            control_session_id="old-session",
        )
        db.add(row)
        db.commit()
        real_crud.update_node(db, row, NodeModify(address="192.0.2.2", port=62052, status=status))
        real_crud.update_node(db, row, NodeModify(address="192.0.2.3", port=62053))

    monkeypatch.setattr(ops, "GetDB", lambda: Session(engine))
    monkeypatch.setattr(ops, "crud", real_crud)
    transport = Mock()
    seen = []

    def add(row):
        seen.append((row.address, row.port, row.api_port, row.protocol))
        ops.xray.nodes[7] = transport
        return transport

    monkeypatch.setattr(ops, "add_node", add)
    connect = Mock(return_value=True)
    monkeypatch.setattr(ops, "_connect_node_impl", connect)
    transport.stop.side_effect = RuntimeError("old endpoint offline") if stop_fails else None
    future = ops.apply_node(7, recover=True)
    scheduler.execute = ops._execute_node_operation
    executor.run()
    if stop_fails:
        with pytest.raises(RuntimeError, match="old endpoint offline"):
            future.result()
        with Session(engine) as db:
            row = db.get(Node, 7)
            assert row.config_apply_pending is True
            assert row.config_apply_endpoint["address"] == "192.0.2.1"
            assert row.message == "old endpoint offline"
            assert row.status == (NodeStatus.disabled if status == NodeStatus.disabled else NodeStatus.error)
        connect.assert_not_called()
        # Lose the registry again, as after a second process restart.
        ops.xray.nodes.clear()
        transport.stop.side_effect = None
        future = ops.apply_node(7, recover=True)
        executor.run()
    assert future.result() is True
    assert [item[:3] for item in seen] == [("192.0.2.1", 62050, 62051)] * (2 if stop_fails else 1)
    assert transport.adopt_control_session.call_count == (2 if stop_fails else 1)
    transport.adopt_control_session.assert_called_with("old-session")
    assert transport.stop.call_count == (2 if stop_fails else 1)
    transport.start.assert_not_called()
    transport.restart.assert_not_called()
    assert connect.call_count == (0 if status == NodeStatus.disabled else 1)
    with Session(engine) as db:
        row = db.get(Node, 7)
        assert row.address == "192.0.2.3"
        assert row.config_apply_pending is False
        assert row.config_apply_endpoint is None


def _save_address_change(engine, Session, Node, NodeModify, real_crud, *, status=None):
    with Session(engine) as db:
        row = Node(
            id=7,
            name="node",
            address="192.0.2.1",
            port=62050,
            api_port=62051,
            status=NodeStatus.connected,
            control_session_id="old-session",
        )
        db.add(row)
        db.commit()
        fields = {"address": "192.0.2.2"}
        if status is not None:
            fields["status"] = status
        real_crud.update_node(db, row, NodeModify(**fields))


def test_unreachable_old_endpoint_connects_to_new_address(monkeypatch, node_database):
    from app.xray.node import NodeAPIError

    lifecycle, ops, state, executor, scheduler = arrange(monkeypatch)
    engine, Session, Node, NodeModify, real_crud = node_database
    _save_address_change(engine, Session, Node, NodeModify, real_crud)
    monkeypatch.setattr(ops, "GetDB", lambda: Session(engine))
    monkeypatch.setattr(ops, "crud", real_crud)
    seen = []

    def add(row):
        seen.append(row.address)
        node = Mock()
        node.stop.side_effect = NodeAPIError(0, "timed out")
        ops.xray.nodes[7] = node
        return node

    monkeypatch.setattr(ops, "add_node", add)

    def connect(*_args, **_kwargs):
        assert 7 not in ops.xray.nodes
        with Session(engine) as db:
            current = db.get(Node, 7)
            assert current.config_apply_endpoint["address"] == "192.0.2.2"
        return True

    connect_mock = Mock(side_effect=connect)
    monkeypatch.setattr(ops, "_connect_node_impl", connect_mock)
    scheduler.execute = ops._execute_node_operation
    future = ops.apply_node(7, recover=True)
    executor.run()

    assert future.result() is True
    assert seen == ["192.0.2.1"]
    connect_mock.assert_called_once()
    with Session(engine) as db:
        row = db.get(Node, 7)
        assert row.address == "192.0.2.2"
        assert row.config_apply_pending is False
        assert row.config_apply_endpoint is None


def test_connection_error_on_old_endpoint_connects_to_new_address(monkeypatch, node_database):
    lifecycle, ops, state, executor, scheduler = arrange(monkeypatch)
    engine, Session, Node, NodeModify, real_crud = node_database
    _save_address_change(engine, Session, Node, NodeModify, real_crud)
    monkeypatch.setattr(ops, "GetDB", lambda: Session(engine))
    monkeypatch.setattr(ops, "crud", real_crud)

    def add(row):
        node = Mock()
        node.stop.side_effect = ConnectionError("timed out while fetching node certificate")
        ops.xray.nodes[7] = node
        return node

    monkeypatch.setattr(ops, "add_node", add)

    def connect(*_args, **_kwargs):
        assert 7 not in ops.xray.nodes
        with Session(engine) as db:
            current = db.get(Node, 7)
            assert current.config_apply_endpoint["address"] == "192.0.2.2"
        return True

    connect_mock = Mock(side_effect=connect)
    monkeypatch.setattr(ops, "_connect_node_impl", connect_mock)
    scheduler.execute = ops._execute_node_operation
    future = ops.apply_node(7, recover=True)
    executor.run()
    assert future.result() is True
    connect_mock.assert_called_once()
    with Session(engine) as db:
        row = db.get(Node, 7)
        assert row.config_apply_pending is False
        assert row.config_apply_endpoint is None


def test_http_error_from_old_endpoint_stays_pending(monkeypatch, node_database):
    from app.xray.node import NodeAPIError

    lifecycle, ops, state, executor, scheduler = arrange(monkeypatch)
    engine, Session, Node, NodeModify, real_crud = node_database
    _save_address_change(engine, Session, Node, NodeModify, real_crud)
    monkeypatch.setattr(ops, "GetDB", lambda: Session(engine))
    monkeypatch.setattr(ops, "crud", real_crud)

    def add(row):
        node = Mock()
        node.stop.side_effect = NodeAPIError(500, "stop failed")
        ops.xray.nodes[7] = node
        return node

    monkeypatch.setattr(ops, "add_node", add)
    connect = Mock(return_value=True)
    monkeypatch.setattr(ops, "_connect_node_impl", connect)
    scheduler.execute = ops._execute_node_operation
    future = ops.apply_node(7, recover=True)
    executor.run()
    with pytest.raises(NodeAPIError):
        future.result()
    connect.assert_not_called()
    with Session(engine) as db:
        row = db.get(Node, 7)
        assert row.config_apply_pending is True
        assert row.config_apply_endpoint["address"] == "192.0.2.1"
        assert row.status == NodeStatus.error


def test_superseded_stop_does_not_connect_to_new_address(monkeypatch, node_database):
    lifecycle, ops, state, executor, scheduler = arrange(monkeypatch)
    engine, Session, Node, NodeModify, real_crud = node_database
    _save_address_change(engine, Session, Node, NodeModify, real_crud)
    monkeypatch.setattr(ops, "GetDB", lambda: Session(engine))
    monkeypatch.setattr(ops, "crud", real_crud)

    def add(row):
        node = Mock()
        node.stop.side_effect = NodeOperationSuperseded()
        ops.xray.nodes[7] = node
        return node

    monkeypatch.setattr(ops, "add_node", add)
    connect = Mock(return_value=True)
    monkeypatch.setattr(ops, "_connect_node_impl", connect)
    scheduler.execute = ops._execute_node_operation
    future = ops.apply_node(7, recover=True)
    executor.run()
    # Планировщик гасит NodeOperationSuperseded и завершает команду как False.
    assert future.result() is False
    connect.assert_not_called()
    with Session(engine) as db:
        row = db.get(Node, 7)
        assert row.config_apply_pending is True
        assert row.config_apply_endpoint["address"] == "192.0.2.1"


def test_local_oserror_on_old_endpoint_stays_pending(monkeypatch, node_database):
    lifecycle, ops, state, executor, scheduler = arrange(monkeypatch)
    engine, Session, Node, NodeModify, real_crud = node_database
    _save_address_change(engine, Session, Node, NodeModify, real_crud)
    monkeypatch.setattr(ops, "GetDB", lambda: Session(engine))
    monkeypatch.setattr(ops, "crud", real_crud)

    def add(row):
        raise OSError("certificate file")

    monkeypatch.setattr(ops, "add_node", add)
    connect = Mock(return_value=True)
    monkeypatch.setattr(ops, "_connect_node_impl", connect)
    scheduler.execute = ops._execute_node_operation
    future = ops.apply_node(7, recover=True)
    executor.run()
    with pytest.raises(OSError, match="certificate file"):
        future.result()
    connect.assert_not_called()
    with Session(engine) as db:
        row = db.get(Node, 7)
        assert row.config_apply_pending is True
        assert row.config_apply_endpoint["address"] == "192.0.2.1"


def test_disabled_same_endpoint_stays_pending_when_unreachable(monkeypatch, node_database):
    from app.xray.node import NodeAPIError

    lifecycle, ops, state, executor, scheduler = arrange(monkeypatch)
    engine, Session, Node, NodeModify, real_crud = node_database
    with Session(engine) as db:
        row = Node(
            id=7,
            name="node",
            address="192.0.2.1",
            port=62050,
            api_port=62051,
            status=NodeStatus.connected,
        )
        db.add(row)
        db.commit()
        real_crud.update_node(db, row, NodeModify(status=NodeStatus.disabled))

    monkeypatch.setattr(ops, "GetDB", lambda: Session(engine))
    monkeypatch.setattr(ops, "crud", real_crud)

    def add(row):
        node = Mock()
        node.stop.side_effect = NodeAPIError(0, "timed out")
        ops.xray.nodes[7] = node
        return node

    monkeypatch.setattr(ops, "add_node", add)
    connect = Mock(return_value=True)
    monkeypatch.setattr(ops, "_connect_node_impl", connect)
    scheduler.execute = ops._execute_node_operation
    future = ops.apply_node(7, recover=True)
    executor.run()
    with pytest.raises(NodeAPIError):
        future.result()
    connect.assert_not_called()
    with Session(engine) as db:
        row = db.get(Node, 7)
        assert row.config_apply_pending is True
        assert row.status == NodeStatus.disabled


def test_disabled_new_address_finishes_when_old_endpoint_unreachable(monkeypatch, node_database):
    lifecycle, ops, state, executor, scheduler = arrange(monkeypatch)
    engine, Session, Node, NodeModify, real_crud = node_database
    _save_address_change(engine, Session, Node, NodeModify, real_crud, status=NodeStatus.disabled)
    monkeypatch.setattr(ops, "GetDB", lambda: Session(engine))
    monkeypatch.setattr(ops, "crud", real_crud)

    def add(row):
        node = Mock()
        node.stop.side_effect = ConnectionError("no route to host")
        ops.xray.nodes[7] = node
        return node

    monkeypatch.setattr(ops, "add_node", add)
    connect = Mock(return_value=True)
    monkeypatch.setattr(ops, "_connect_node_impl", connect)
    scheduler.execute = ops._execute_node_operation
    future = ops.apply_node(7, recover=True)
    executor.run()
    assert future.result() is True
    connect.assert_not_called()
    with Session(engine) as db:
        row = db.get(Node, 7)
        assert row.address == "192.0.2.2"
        assert row.status == NodeStatus.disabled
        assert row.config_apply_pending is False
        assert row.config_apply_endpoint is None


@pytest.mark.parametrize("fails", [False, True])
def test_rpyc_hard_restart_initializes_api_before_started(monkeypatch, fails):
    import app.xray.node as module

    node = module.RPyCXRayNode.__new__(module.RPyCXRayNode)
    node.address, node.api_port, node._node_cert = "192.0.2.1", 62051, "certificate"
    node.connection = Mock(closed=False)
    node.started, node._api = False, None
    api = Mock()
    wait = Mock(side_effect=ConnectionError("grpc unavailable") if fails else None, return_value=api)
    monkeypatch.setattr(module, "wait_for_grpc_ready", wait)
    if fails:
        with pytest.raises(ConnectionError):
            node.restart(config_json="config")
        assert node.started is False and node._api is None
    else:
        node.restart(config_json="config")
        assert node.started is True and node._api is api
    node.connection.root.restart.assert_called_once_with("config")
    wait.assert_called_once()


def test_superseded_rest_does_not_fetch_peer_certificate(monkeypatch):
    import app.xray.node as module
    from app.xray.node_operations import NodeOperationSuperseded
    from tests.test_node_soft_reconnect import _make_node

    node = _make_node()
    node._node_cert = None
    node._session_id = "sid"
    node._operation_check = Mock(side_effect=NodeOperationSuperseded())
    fetch = Mock()
    monkeypatch.setattr(module, "fetch_server_certificate", fetch)
    with pytest.raises(NodeOperationSuperseded):
        node.try_restore()
    fetch.assert_not_called()


def test_saved_endpoint_is_moved_before_starting_next_target(monkeypatch, tmp_path):
    lifecycle, ops, state, executor, scheduler = arrange(monkeypatch)
    from contextlib import contextmanager

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.db import crud as real_crud
    from app.db.base import Base
    from app.db.models import Node
    from app.models.node import NodeModify

    engine = create_engine(f"sqlite:///{tmp_path / 'transition.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        row = Node(
            id=7,
            name="node",
            address="192.0.2.1",
            port=62050,
            api_port=62051,
            status=NodeStatus.connected,
            control_session_id="old-session",
        )
        db.add(row)
        db.commit()
        real_crud.update_node(db, row, NodeModify(address="192.0.2.2"))

    @contextmanager
    def get_db():
        with Session(engine) as db:
            yield db

    monkeypatch.setattr(ops, "GetDB", get_db)
    monkeypatch.setattr(ops, "crud", real_crud)
    monkeypatch.setattr(lifecycle, "crud", real_crud)
    stopped = []

    def add(row):
        node = Mock()
        node.stop.side_effect = lambda: stopped.append(row.address)
        ops.xray.nodes[7] = node
        return node

    monkeypatch.setattr(ops, "add_node", add)

    def connect(*_args, **_kwargs):
        with Session(engine) as db:
            row = db.get(Node, 7)
            assert row.config_apply_endpoint["address"] == "192.0.2.2"
            lifecycle.modify_node(db, row, NodeModify(address="192.0.2.3", status=NodeStatus.disabled), Mock())
        return True

    monkeypatch.setattr(ops, "_connect_node_impl", connect)
    scheduler.execute = ops._execute_node_operation
    future = ops.apply_node(7)
    executor.run()
    assert future.result() is False
    # Simulate a process restart: lose local registry and in-memory intents.
    ops.xray.nodes.clear()
    scheduler = NodeOperationScheduler(executor, ops._execute_node_operation, lambda: {}, concurrency=1)
    monkeypatch.setattr(ops, "get_node_scheduler", lambda: scheduler)
    executor.jobs.clear()
    future = ops.apply_node(7, recover=True)
    executor.run()
    assert future.result() is True
    assert stopped == ["192.0.2.1", "192.0.2.2"]
    engine.dispose()


def test_commit_and_apply_admission_share_metadata_lock(monkeypatch):
    import threading

    lifecycle, ops, state, executor, scheduler = arrange(monkeypatch)
    admitted, attempting, entered, finish = (threading.Event() for _ in range(4))
    real_apply = ops.apply_node
    errors = []

    def delayed_apply(*args, **kwargs):
        admitted.set()
        assert finish.wait(3)
        return real_apply(*args, **kwargs)

    monkeypatch.setattr(ops, "apply_node", delayed_apply)
    lifecycle.crud.update_node.return_value = SimpleNamespace(id=7)

    def save():
        try:
            lifecycle.modify_node(Mock(), SimpleNamespace(id=7), Mock(), Mock())
        except BaseException as exc:
            errors.append(exc)

    def newer():
        attempting.set()
        with scheduler.metadata(7):
            entered.set()

    first = threading.Thread(target=save)
    second = threading.Thread(target=newer)
    first.start()
    try:
        assert admitted.wait(3)
        second.start()
        assert attempting.wait(3)
        assert not entered.wait(0.1)
    finally:
        finish.set()
        first.join(3)
        if second.ident is not None:
            second.join(3)
    assert not errors and entered.is_set()
    assert not first.is_alive() and not second.is_alive()


def test_new_inbound_locks_are_sorted_across_routes(monkeypatch, tmp_path):
    load_route(monkeypatch)
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.db import crud as real_crud
    from app.db.base import Base
    from app.db.models import Node
    from app.models.node import CascadeRouteModel, NodeModify

    engine = create_engine(f"sqlite:///{tmp_path / 'tag-order.db'}")
    Base.metadata.create_all(engine)
    helper = real_crud.get_or_create_inbound
    calls = []

    def resolve(db, tag, **kwargs):
        calls.append(tag)
        return helper(db, tag, **kwargs)

    monkeypatch.setattr(real_crud, "get_or_create_inbound", resolve)
    with Session(engine) as db:
        row = Node(id=7, name="node", address="192.0.2.1", port=62050, api_port=62051)
        db.add(row)
        db.add(Node(id=8, name="exit", address="192.0.2.2", port=62050, api_port=62051))
        db.commit()
        real_crud.update_node(
            db,
            row,
            NodeModify(
                inbounds=["z", "b"],
                cascade_routes=[CascadeRouteModel(exit_node_id=8, entry_inbound_tag="a", cascade_inbound_tag="c")],
            ),
        )
        assert calls[:4] == ["a", "b", "c", "z"]
        assert [inbound.tag for inbound in row.inbounds] == ["b", "z"]
    engine.dispose()


def test_old_endpoint_session_publication_does_not_replace_target_session(monkeypatch, tmp_path):
    _, ops, _, _, _ = arrange(monkeypatch)
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.db import crud as real_crud
    from app.db.base import Base
    from app.db.models import Node
    from app.models.node import NodeModify

    engine = create_engine(f"sqlite:///{tmp_path / 'session-endpoint.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        row = Node(
            id=7,
            name="node",
            address="192.0.2.1",
            port=62050,
            api_port=62051,
            status=NodeStatus.connected,
            control_session_id="old-session",
        )
        db.add(row)
        db.commit()
        real_crud.update_node(db, row, NodeModify(address="192.0.2.2", status=NodeStatus.disabled))
        previous = dict(row.config_apply_endpoint)
    monkeypatch.setattr(ops, "GetDB", lambda: Session(engine))
    monkeypatch.setattr(ops, "crud", real_crud)
    endpoint = {key: previous[key] for key in ("address", "port", "api_port", "protocol")}
    ops._persist_control_session(7, "old-stop-session", endpoint=endpoint)
    with Session(engine) as db:
        row = db.get(Node, 7)
        assert row.config_apply_endpoint["control_session_id"] == "old-stop-session"
        assert row.control_session_id is None
    ops._persist_control_session(7, None, endpoint=endpoint)
    with Session(engine) as db:
        assert db.get(Node, 7).config_apply_endpoint["control_session_id"] is None
    engine.dispose()


def test_reenable_on_new_endpoint_does_not_stop_confirmed_disabled_server(monkeypatch, tmp_path):
    lifecycle, ops, state, executor, scheduler = arrange(monkeypatch)
    from contextlib import contextmanager

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.db import crud as real_crud
    from app.db.base import Base
    from app.db.models import Node
    from app.models.node import NodeModify

    engine = create_engine(f"sqlite:///{tmp_path / 'reenable.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        row = Node(
            id=7,
            name="node",
            address="192.0.2.1",
            port=62050,
            api_port=62051,
            status=NodeStatus.disabled,
            config_apply_pending=False,
        )
        db.add(row)
        db.commit()
        real_crud.update_node(db, row, NodeModify(address="192.0.2.2", status=NodeStatus.connecting))

    @contextmanager
    def get_db():
        with Session(engine) as db:
            yield db

    monkeypatch.setattr(ops, "GetDB", get_db)
    monkeypatch.setattr(ops, "crud", real_crud)
    add = Mock(side_effect=ConnectionError("old server is gone"))
    monkeypatch.setattr(ops, "add_node", add)
    connect = Mock(return_value=True)
    monkeypatch.setattr(ops, "_connect_node_impl", connect)
    scheduler.execute = ops._execute_node_operation
    future = ops.apply_node(7)
    executor.run()
    assert future.result() is True
    add.assert_not_called()
    connect.assert_called_once()
    engine.dispose()


@pytest.mark.parametrize("kind", [OperationKind.SOFT, OperationKind.HARD, OperationKind.RESTART])
def test_reconnect_with_pending_settings_continues_apply_after_accounting(monkeypatch, kind):
    _, ops, state, executor, scheduler = arrange(monkeypatch)
    row = SimpleNamespace(id=7, config_apply_pending=True)
    monkeypatch.setattr(ops, "GetDB", Mock(return_value=MagicMock()))
    monkeypatch.setattr(ops, "crud", Mock(get_node_by_id=Mock(return_value=row)))
    connect, restart, apply = Mock(return_value=True), Mock(return_value=True), Mock(return_value=True)
    monkeypatch.setattr(ops, "_connect_node_impl", connect)
    monkeypatch.setattr(ops, "_restart_node_impl", restart)
    monkeypatch.setattr(ops, "_apply_node_impl", apply)
    epoch = state.observe_nodes({7: "new"})[7]
    release = state.acquire_collection(7, epoch)
    scheduler.execute = ops._execute_node_operation
    future = scheduler.request(7, kind, manual=True)
    executor.run()
    assert future.result() is False
    connect.assert_not_called()
    restart.assert_not_called()
    assert not executor.jobs
    release()
    executor.run()
    apply.assert_called_once()


def _pending_stop_endpoint(node_database, status, address):
    engine, Session, Node, NodeModify, crud = node_database
    with Session(engine) as db:
        row = Node(
            id=7,
            name="node",
            address="192.0.2.1",
            port=62050,
            api_port=62051,
            status=NodeStatus.connected,
            control_session_id="old-session",
        )
        db.add(row)
        db.commit()
        crud.update_node(db, row, NodeModify(address=address, status=status))
        return dict(row.config_apply_endpoint)


@pytest.mark.parametrize("status", [NodeStatus.disabled, NodeStatus.connecting])
@pytest.mark.parametrize("edit_during_stop", [False, True])
def test_confirmed_stop_survives_crash_before_next_apply_step(monkeypatch, node_database, status, edit_during_stop):
    """После stop старый сервер может исчезнуть: recovery не требует второго stop."""
    lifecycle, ops, state, executor, scheduler = arrange(monkeypatch)
    engine, Session, Node, NodeModify, real_crud = node_database
    _pending_stop_endpoint(node_database, status, "192.0.2.2")
    monkeypatch.setattr(ops, "GetDB", lambda: Session(engine))
    monkeypatch.setattr(ops, "crud", real_crud)
    monkeypatch.setattr(lifecycle, "crud", real_crud)
    transport = Mock()
    stopped = []

    def stop():
        if edit_during_stop:
            with Session(engine) as db:
                lifecycle.modify_node(db, db.get(Node, 7), NodeModify(address="192.0.2.3", status=status), Mock())
        stopped.append(True)

    transport.stop.side_effect = stop
    monkeypatch.setattr(ops, "add_node", Mock(return_value=transport))

    class ProcessCrash(BaseException):
        pass

    def remove(*_args, **_kwargs):
        if stopped:
            raise ProcessCrash()

    monkeypatch.setattr(ops, "remove_node", remove)
    scheduler.execute = ops._execute_node_operation
    first = ops.apply_node(7)
    executor.run()
    with pytest.raises(ProcessCrash):
        first.result()
    with Session(engine) as db:
        row = db.get(Node, 7)
        assert row.config_apply_pending is True
        assert row.config_apply_endpoint["address"] == "192.0.2.1"
        assert row.config_apply_endpoint["stopped"] is True
        assert row.address == ("192.0.2.3" if edit_during_stop else "192.0.2.2")

    # Lose the old worker/registry. Server A is now unavailable forever.
    ops.xray.nodes.clear()
    executor = Executor()
    scheduler = NodeOperationScheduler(executor, ops._execute_node_operation, lambda: {}, concurrency=1)
    monkeypatch.setattr(ops, "get_node_scheduler", lambda: scheduler)
    old_server = Mock(side_effect=AssertionError("stopped endpoint must not be contacted again"))
    monkeypatch.setattr(ops, "add_node", old_server)
    monkeypatch.setattr(ops, "remove_node", Mock())
    connect = Mock(return_value=True)
    monkeypatch.setattr(ops, "_connect_node_impl", connect)
    recovery = ops.apply_node(7, recover=True)
    executor.run()
    assert recovery.result() is True
    old_server.assert_not_called()
    transport.stop.assert_called_once()
    assert connect.call_count == (0 if status == NodeStatus.disabled else 1)
    with Session(engine) as db:
        row = db.get(Node, 7)
        assert row.config_apply_pending is False and row.config_apply_endpoint is None


@pytest.mark.parametrize("replaced", [False, True])
def test_stop_ack_preserves_latest_session_and_does_not_mark_another_endpoint(monkeypatch, node_database, replaced):
    """Подтверждение относится к остановленному серверу, не к более новой цели."""
    _, ops, _, _, _ = arrange(monkeypatch)
    engine, Session, Node, NodeModify, real_crud = node_database
    old_endpoint = _pending_stop_endpoint(node_database, NodeStatus.disabled, "192.0.2.1")
    monkeypatch.setattr(ops, "GetDB", lambda: Session(engine))
    monkeypatch.setattr(ops, "crud", real_crud)
    monkeypatch.setattr(ops, "remove_node", Mock())
    transport = Mock()

    def stop():
        with Session(engine) as db:
            current = db.get(Node, 7)
            current.config_apply_endpoint = {
                **current.config_apply_endpoint,
                "address": "192.0.2.2" if replaced else "192.0.2.1",
                "control_session_id": "latest-session",
            }
            db.commit()

    transport.stop.side_effect = stop
    monkeypatch.setattr(ops, "add_node", Mock(return_value=transport))
    with Session(engine) as db:
        ops._stop_apply_endpoint(7, db.get(Node, 7), old_endpoint)
    with Session(engine) as db:
        endpoint = db.get(Node, 7).config_apply_endpoint
        assert endpoint["control_session_id"] == "latest-session"
        assert endpoint["stopped"] is (not replaced)
