"""Exclusive connect slot + HARD retry without takeover storm."""

import sys
import threading
import types
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

from app.xray.node_operations import NodeOperationScheduler

for _name, _module in list(sys.modules.items()):
    if _name.startswith("app.") and not hasattr(_module, "__file__") and not hasattr(_module, "__path__"):
        del sys.modules[_name]

_share_stub = types.ModuleType("app.subscription.share")
_share_stub.generate_v2ray_links = lambda *args, **kwargs: []
sys.modules.setdefault("app.subscription.share", _share_stub)

from app.models.node import NodeStatus  # noqa: E402
from app.xray import operations  # noqa: E402

if sys.modules.get("app.subscription.share") is _share_stub:
    del sys.modules["app.subscription.share"]


def _reset_slots():
    with operations._connecting_nodes_lock:
        operations._connecting_nodes.clear()
        operations._connecting_started_at.clear()
        operations._connecting_generation.clear()


def test_force_does_not_steal_live_connect_slot():
    _reset_slots()
    gen1 = operations._acquire_connect_slot(149, force=False)
    assert gen1 is not None
    assert operations.is_connect_in_progress(149)

    # Former bug: force=True discarded the lock and started a parallel HARD.
    assert operations._acquire_connect_slot(149, force=True) is None
    assert operations.is_connect_in_progress(149)

    operations._release_connect_slot(149, gen1)
    assert not operations.is_connect_in_progress(149)


def test_stale_lock_cannot_be_reclaimed_before_worker_completion():
    _reset_slots()
    gen1 = operations._acquire_connect_slot(149)
    operations._connecting_started_at[149] = 0
    assert operations._acquire_connect_slot(149, force=True) is None
    operations._release_connect_slot(149, gen1)
    assert operations._acquire_connect_slot(149, force=True) is not None
    _reset_slots()


def test_invalidation_does_not_release_a_running_execution_guard():
    _reset_slots()
    gen1 = operations._acquire_connect_slot(149)
    operations.invalidate_connect_slot(149)
    assert operations.is_connect_in_progress(149)
    assert operations._acquire_connect_slot(149, force=True) is None
    operations._release_connect_slot(149, gen1)
    operations.invalidate_connect_slot(149)
    assert operations._acquire_connect_slot(149, force=True) is not None
    _reset_slots()


def test_add_node_does_not_invalidate_connect_slot():
    """Regression: Edit → connect → add_node must not clear the in-flight HARD lock."""
    _reset_slots()
    gen = operations._acquire_connect_slot(6, force=True)
    assert operations.is_connect_in_progress(6)

    dbnode = MagicMock()
    dbnode.id = 6
    dbnode.address = "10.0.0.1"
    dbnode.port = 62050
    dbnode.api_port = 62051
    dbnode.protocol = "rest"
    dbnode.usage_coefficient = 1.0

    fake_node = MagicMock()
    with (
        patch.object(operations, "get_tls", return_value={"key": "k", "certificate": "c"}),
        patch.object(operations, "XRayNode", return_value=fake_node),
        patch.object(operations, "xray") as xray_mod,
    ):
        xray_mod.nodes = {6: MagicMock()}
        operations.add_node(dbnode)

    assert operations.is_connect_in_progress(6)
    operations._release_connect_slot(6, gen)
    assert not operations.is_connect_in_progress(6)


def test_hard_retry_reuses_session_without_second_connect():
    """After /connect ok + /restart write timeout, attempt 2 must only /restart."""
    dbnode = MagicMock()
    dbnode.id = 149
    dbnode.name = "usnyc"
    dbnode.status = NodeStatus.error
    dbnode.inbounds = []

    node = MagicMock()
    node._session_id = None

    def connect_side_effect():
        node._session_id = "sess-after-connect"

    node.connect.side_effect = connect_side_effect
    node.restart.side_effect = [Exception("write timed out"), None]
    node.get_version.return_value = "26.3.27"

    with (
        patch.object(operations, "_acquire_connect_slot", return_value=1),
        patch.object(operations, "_release_connect_slot"),
        patch.object(operations, "_connect_semaphore") as sem,
        patch.object(operations, "GetDB") as get_db,
        patch.object(operations, "crud") as crud,
        patch.object(operations, "_change_node_status", return_value=True),
        patch.object(operations, "xray") as xray_mod,
        patch.object(operations, "node_config_json", return_value="{}"),
        patch.object(operations, "_cascade_kwargs", return_value={"role": "direct"}),
        patch.object(operations, "_blocked_user_ids", return_value=set()),
        patch.object(operations, "_cleanup_node_connection") as cleanup,
        patch.object(operations, "XRAY_NODE_CONNECT_RETRIES", 2),
        patch.object(operations, "XRAY_NODE_CONNECT_RETRY_DELAY", 0),
    ):
        sem.acquire = MagicMock()
        sem.release = MagicMock()
        get_db.return_value.__enter__.return_value = MagicMock()
        get_db.return_value.__exit__.return_value = None
        crud.get_node_by_id.return_value = dbnode
        xray_mod.nodes = {149: node}

        operations._connect_node_impl(149, config=MagicMock(), force=True)

    assert node.connect.call_count == 1
    assert node.restart.call_count == 2
    assert cleanup.call_count == 1


def test_manual_hard_reconnect_waits_for_active_soft_connect():
    """Manual Reconnect must not issue /connect while an earlier attempt uses the node."""
    _reset_slots()
    dbnode = MagicMock()
    dbnode.id = 149
    dbnode.name = "usnyc"
    dbnode.status = NodeStatus.connecting
    dbnode.inbounds = []
    dbnode.control_session_id = None

    soft_started = threading.Event()
    allow_soft_finish = threading.Event()
    hard_connect_started = threading.Event()
    node = MagicMock()
    node._session_id = "soft-session"
    node.get_version.return_value = "26.3.27"

    def slow_restore():
        soft_started.set()
        assert allow_soft_finish.wait(5), "soft connect did not finish"
        return True

    def hard_connect():
        hard_connect_started.set()
        node._session_id = "hard-session"

    node.try_restore.side_effect = slow_restore
    node.connect.side_effect = hard_connect

    with (
        patch.object(operations, "GetDB") as get_db,
        patch.object(operations, "crud") as crud,
        patch.object(operations, "_change_node_status", return_value=True),
        patch.object(operations, "xray") as xray_mod,
        patch.object(operations, "node_config_json", return_value="{}"),
        patch.object(operations, "_cascade_kwargs", return_value={"role": "direct"}),
        patch.object(operations, "_blocked_user_ids", return_value=set()),
        patch.object(operations, "XRAY_NODE_CONNECT_RETRIES", 1),
        patch.object(operations, "XRAY_NODE_CONNECT_RETRY_DELAY", 0),
    ):
        get_db.return_value.__enter__.return_value = MagicMock()
        get_db.return_value.__exit__.return_value = None
        crud.get_node_by_id.return_value = dbnode
        xray_mod.nodes = {149: node}

        with ThreadPoolExecutor(max_workers=1) as executor:
            controller = NodeOperationScheduler(
                executor,
                operations._execute_node_operation,
                lambda: MagicMock(),
                concurrency=1,
            )
            with patch.object(operations, "get_node_scheduler", return_value=controller):
                soft = operations.connect_node(149)
                assert soft_started.wait(5)
                hard = operations.connect_node(149, force=True, manual=True)
                try:
                    assert not hard_connect_started.is_set()
                    assert hard is not soft and not hard.done()
                finally:
                    allow_soft_finish.set()
                soft.result(timeout=5)
                hard.result(timeout=5)

    assert hard_connect_started.is_set()


def test_parallel_node_restarts_are_serialized():
    """Two manual restarts must not send overlapping REST /restart commands."""
    dbnode = MagicMock()
    dbnode.id = 149
    dbnode.name = "usnyc"
    dbnode.inbounds = []
    first_restart_started = threading.Event()
    allow_first_restart_finish = threading.Event()
    second_restart_started = threading.Event()
    restart_calls = 0
    node = MagicMock()
    node.connected = True

    def restart(**_kwargs):
        nonlocal restart_calls
        restart_calls += 1
        if restart_calls == 1:
            first_restart_started.set()
            assert allow_first_restart_finish.wait(5), "first restart did not finish"
        else:
            second_restart_started.set()

    node.restart.side_effect = restart

    with (
        patch.object(operations, "GetDB") as get_db,
        patch.object(operations, "crud") as crud,
        patch.object(operations, "xray") as xray_mod,
        patch.object(operations, "node_config_json", return_value="{}"),
        patch.object(operations, "_cascade_kwargs", return_value={"role": "direct"}),
        patch.object(operations, "_blocked_user_ids", return_value=set()),
    ):
        get_db.return_value.__enter__.return_value = MagicMock()
        get_db.return_value.__exit__.return_value = None
        crud.get_node_by_id.return_value = dbnode
        xray_mod.nodes = {149: node}

        first = threading.Thread(
            target=lambda node_id, config: operations._execute_node_operation(
                node_id, operations.OperationKind.RESTART, lambda: config
            ),
            args=(149, MagicMock()),
        )
        second = threading.Thread(
            target=lambda node_id, config: operations._execute_node_operation(
                node_id, operations.OperationKind.RESTART, lambda: config
            ),
            args=(149, MagicMock()),
        )
        first.start()
        assert first_restart_started.wait(5)
        second.start()
        try:
            assert not second_restart_started.wait(0.2)
        finally:
            allow_first_restart_finish.set()
            first.join(5)
            second.join(5)

    assert not first.is_alive() and not second.is_alive()
    assert restart_calls == 2


def test_node_connects_respect_parallelism_limit():
    """A startup wave runs no more REST connects than the configured semaphore allows."""
    _reset_slots()
    dbnodes = {}
    nodes = {}
    two_connects_started = threading.Event()
    release_connects = threading.Event()
    active = 0
    peak_active = 0
    active_lock = threading.Lock()

    for node_id in (1, 2, 3):
        dbnode = MagicMock()
        dbnode.id = node_id
        dbnode.name = f"node-{node_id}"
        dbnode.status = NodeStatus.error
        dbnode.inbounds = []
        dbnode.control_session_id = None
        dbnodes[node_id] = dbnode

        node = MagicMock()
        node._session_id = None
        node.get_version.return_value = "26.3.27"

        def connect(*, _node=node):
            nonlocal active, peak_active
            with active_lock:
                active += 1
                peak_active = max(peak_active, active)
                if active == 2:
                    two_connects_started.set()
            assert release_connects.wait(5), "connect wave was not released"
            with active_lock:
                active -= 1
            _node._session_id = "connected"

        node.connect.side_effect = connect
        nodes[node_id] = node

    with (
        patch.object(operations, "GetDB") as get_db,
        patch.object(operations, "crud") as crud,
        patch.object(operations, "_change_node_status", return_value=True),
        patch.object(operations, "xray") as xray_mod,
        patch.object(operations, "node_config_json", return_value="{}"),
        patch.object(operations, "_cascade_kwargs", return_value={"role": "direct"}),
        patch.object(operations, "_blocked_user_ids", return_value=set()),
        patch.object(operations, "XRAY_NODE_CONNECT_RETRIES", 1),
        patch.object(operations, "XRAY_NODE_CONNECT_RETRY_DELAY", 0),
        patch.object(operations, "_connect_semaphore", threading.BoundedSemaphore(2)),
    ):
        get_db.return_value.__enter__.return_value = MagicMock()
        get_db.return_value.__exit__.return_value = None
        crud.get_node_by_id.side_effect = lambda _db, node_id: dbnodes[node_id]
        xray_mod.nodes = nodes

        threads = [
            threading.Thread(target=operations._connect_node_impl, args=(node_id, MagicMock(), True))
            for node_id in dbnodes
        ]
        for thread in threads:
            thread.start()
        assert two_connects_started.wait(5)
        assert peak_active == 2
        release_connects.set()
        for thread in threads:
            thread.join(5)

    assert not any(thread.is_alive() for thread in threads)
    assert peak_active == 2
    assert all(node.connect.call_count == 1 for node in nodes.values())
