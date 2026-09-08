"""Exclusive connect slot + HARD retry without takeover storm."""

import sys
import time
import types
from unittest.mock import MagicMock, patch

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


def test_stale_lock_can_be_reclaimed():
    _reset_slots()
    gen1 = operations._acquire_connect_slot(149, force=False)
    with operations._connecting_nodes_lock:
        operations._connecting_started_at[149] = time.time() - operations.XRAY_NODE_CONNECT_STALE_TIMEOUT - 1

    gen2 = operations._acquire_connect_slot(149, force=True)
    assert gen2 is not None and gen2 != gen1
    # Old owner must not clear the new lock.
    operations._release_connect_slot(149, gen1)
    assert operations.is_connect_in_progress(149)
    operations._release_connect_slot(149, gen2)
    assert not operations.is_connect_in_progress(149)


def test_invalidate_connect_slot_allows_new_owner():
    _reset_slots()
    gen1 = operations._acquire_connect_slot(149, force=False)
    operations.invalidate_connect_slot(149)
    assert not operations.is_connect_in_progress(149)

    gen2 = operations._acquire_connect_slot(149, force=True)
    assert gen2 is not None
    operations._release_connect_slot(149, gen1)  # stale finally
    assert operations.is_connect_in_progress(149)
    operations._release_connect_slot(149, gen2)


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
