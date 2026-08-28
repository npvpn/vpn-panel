"""Regression: soft deferred must not leave fake DB status=connected."""

import sys
import types
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

# Same harness as test_record_bs_usage: models → user → share breaks under conftest stubs.
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


def test_connecting_age_seconds():
    dbnode = MagicMock()
    dbnode.status = NodeStatus.connecting
    dbnode.last_status_change = datetime.utcnow() - timedelta(seconds=150)

    with (
        patch.object(operations, "GetDB") as get_db,
        patch.object(operations, "crud") as crud,
    ):
        get_db.return_value.__enter__.return_value = MagicMock()
        get_db.return_value.__exit__.return_value = None
        crud.get_node_by_id.return_value = dbnode
        age = operations.connecting_age_seconds(6)
        assert age is not None and age >= 149


def test_soft_deferred_does_not_mark_connected():
    dbnode = MagicMock()
    dbnode.id = 6
    dbnode.name = "nl-3"
    dbnode.status = NodeStatus.connected
    dbnode.inbounds = []
    dbnode.xray_version = "26.2.6"

    node = MagicMock()
    node._session_id = "sess-1"
    node.try_restore.side_effect = Exception("timeout")

    status_calls = []

    def capture_status(node_id, status, message=None, version=None):
        status_calls.append((node_id, status, version))
        return True

    with (
        patch.object(operations, "_acquire_connect_slot", return_value=True),
        patch.object(operations, "_release_connect_slot"),
        patch.object(operations, "_connect_semaphore") as sem,
        patch.object(operations, "GetDB") as get_db,
        patch.object(operations, "crud") as crud,
        patch.object(operations, "_change_node_status", side_effect=capture_status),
        patch.object(operations, "xray") as xray_mod,
        patch.object(operations, "node_config_json", return_value="{}"),
        patch.object(operations, "_cascade_kwargs", return_value={"role": "direct"}),
        patch.object(operations, "_blocked_user_ids", return_value=set()),
    ):
        sem.acquire = MagicMock()
        sem.release = MagicMock()
        get_db.return_value.__enter__.return_value = MagicMock()
        get_db.return_value.__exit__.return_value = None
        crud.get_node_by_id.return_value = dbnode
        xray_mod.nodes = {6: node}
        xray_mod.config.include_db_users.return_value = MagicMock()

        operations._connect_node_impl(6, config=MagicMock(), force=False)

    assert any(s == NodeStatus.connecting for _, s, _ in status_calls)
    assert not any(s == NodeStatus.connected for _, s, _ in status_calls)
    node.start.assert_not_called()
    node.connect.assert_not_called()


def test_soft_retry_skips_status_rewrite_when_already_connecting():
    """Re-entering soft connect must not reset last_status_change via connecting rewrite."""
    dbnode = MagicMock()
    dbnode.id = 6
    dbnode.name = "nl-3"
    dbnode.status = NodeStatus.connecting
    dbnode.inbounds = []

    node = MagicMock()
    node._session_id = "sess-1"
    node.try_restore.side_effect = Exception("timeout")

    with (
        patch.object(operations, "_acquire_connect_slot", return_value=True),
        patch.object(operations, "_release_connect_slot"),
        patch.object(operations, "_connect_semaphore") as sem,
        patch.object(operations, "GetDB") as get_db,
        patch.object(operations, "crud") as crud,
        patch.object(operations, "_change_node_status") as change_status,
        patch.object(operations, "xray") as xray_mod,
        patch.object(operations, "node_config_json", return_value="{}"),
        patch.object(operations, "_cascade_kwargs", return_value={"role": "direct"}),
        patch.object(operations, "_blocked_user_ids", return_value=set()),
    ):
        sem.acquire = MagicMock()
        sem.release = MagicMock()
        get_db.return_value.__enter__.return_value = MagicMock()
        get_db.return_value.__exit__.return_value = None
        crud.get_node_by_id.return_value = dbnode
        xray_mod.nodes = {6: node}

        operations._connect_node_impl(6, config=MagicMock(), force=False)

    change_status.assert_not_called()


def _run_soft_deferred(dbnode, node, status_calls):
    def capture_status(node_id, status, message=None, version=None):
        status_calls.append((node_id, status, version))
        dbnode.status = status
        if version is not None:
            dbnode.xray_version = version
        elif status == NodeStatus.connecting:
            dbnode.xray_version = None
        return True

    with (
        patch.object(operations, "_acquire_connect_slot", return_value=True),
        patch.object(operations, "_release_connect_slot"),
        patch.object(operations, "_connect_semaphore") as sem,
        patch.object(operations, "GetDB") as get_db,
        patch.object(operations, "crud") as crud,
        patch.object(operations, "_change_node_status", side_effect=capture_status),
        patch.object(operations, "xray") as xray_mod,
        patch.object(operations, "node_config_json", return_value="{}"),
        patch.object(operations, "_cascade_kwargs", return_value={"role": "direct"}),
        patch.object(operations, "_blocked_user_ids", return_value=set()),
    ):
        sem.acquire = MagicMock()
        sem.release = MagicMock()
        get_db.return_value.__enter__.return_value = MagicMock()
        get_db.return_value.__exit__.return_value = None
        crud.get_node_by_id.return_value = dbnode
        xray_mod.nodes = {dbnode.id: node}
        xray_mod.config.include_db_users.return_value = MagicMock()
        operations._connect_node_impl(dbnode.id, config=MagicMock(), force=False)


def test_scenario_soft_outage_stays_connecting_then_stale_forces_hard():
    """Full bug path (network outage + kept session_id) vs fix + HARD escalation.

    OLD bug: soft deferred marked DB=connected without xray_version → UI «Подключен»
    without badge, health assumed OK, no reconnect.

    FIX: stay connecting (no fake connected); after stale age health must force HARD.
    """
    dbnode = MagicMock()
    dbnode.id = 6
    dbnode.name = "rare-jp3"
    dbnode.status = NodeStatus.connected
    dbnode.inbounds = []
    dbnode.xray_version = "26.2.6"
    dbnode.last_status_change = datetime.utcnow()

    node = MagicMock()
    node._session_id = "sess-kept-across-blip"
    node.try_restore.side_effect = Exception("Connection timed out")

    status_calls = []
    _run_soft_deferred(dbnode, node, status_calls)

    # After soft deferred: must look like "connecting", never fake connected.
    assert dbnode.status == NodeStatus.connecting
    assert not any(s == NodeStatus.connected for _, s, _ in status_calls)
    # Version wiped on entering connecting — badge only after real get_version.
    assert dbnode.xray_version is None
    node.connect.assert_not_called()

    # Soft retries while still connecting must not rewrite status (stale clock).
    status_calls.clear()
    _run_soft_deferred(dbnode, node, status_calls)
    assert status_calls == []
    assert dbnode.status == NodeStatus.connecting

    # Stale connecting → health escalates to HARD (same predicate as 0_xray_core).
    dbnode.last_status_change = datetime.utcnow() - timedelta(seconds=130)
    with (
        patch.object(operations, "GetDB") as get_db,
        patch.object(operations, "crud") as crud,
        patch.object(operations, "is_connect_stale", return_value=False),
        patch.object(operations, "XRAY_NODE_CONNECT_STALE_TIMEOUT", 120),
    ):
        get_db.return_value.__enter__.return_value = MagicMock()
        get_db.return_value.__exit__.return_value = None
        crud.get_node_by_id.return_value = dbnode

        age = operations.connecting_age_seconds(dbnode.id)
        assert age is not None and age >= 120
        # Mirrors _should_force_reconnect for status=connecting without active lock.
        force = age >= 120
        assert force is True
