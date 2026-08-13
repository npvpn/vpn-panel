"""Soft reconnect: keep REST session across transient network blips."""

import sys
from unittest.mock import MagicMock, patch

import pytest

# Heavy imports behind ReSTXRayNode — stub before first import of app.xray.node.
_stubs = {
    "app.xray.config": MagicMock(XRayConfig=object),
    "app.xray.node_config": MagicMock(inline_local_certificates=lambda c: c),
    "xray_api": MagicMock(),
    "rpyc": MagicMock(),
    "grpc": MagicMock(),
    "websocket": MagicMock(
        WebSocketConnectionClosedException=Exception,
        WebSocketTimeoutException=Exception,
        create_connection=MagicMock(),
    ),
}
for name, mod in _stubs.items():
    sys.modules.setdefault(name, mod)

from app.xray.node import NodeAPIError, ReSTXRayNode


def _make_node() -> ReSTXRayNode:
    node = ReSTXRayNode.__new__(ReSTXRayNode)
    node.address = "10.0.0.1"
    node.port = 62050
    node.api_port = 62051
    node._session_id = "11111111-1111-1111-1111-111111111111"
    node._node_cert = "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"
    node._node_certfile = MagicMock()
    node._started = False
    node._api = None
    node._grpc_lock = __import__("threading").Lock()
    node.session = MagicMock()
    node._rest_api_url = "https://10.0.0.1:62050"
    return node


def test_is_session_invalid_detects_403_and_mismatch():
    assert ReSTXRayNode._is_session_invalid(NodeAPIError(403, "Session ID mismatch."))
    assert ReSTXRayNode._is_session_invalid(NodeAPIError(403, {"msg": "denied"}))
    assert not ReSTXRayNode._is_session_invalid(NodeAPIError(0, "Connection timed out"))
    assert not ReSTXRayNode._is_session_invalid(NodeAPIError(503, "Xray is started already"))


def test_connected_keeps_session_on_transport_error():
    node = _make_node()
    with patch.object(node, "make_request", side_effect=NodeAPIError(0, "Connection timed out")):
        assert node.connected is False
    assert node._session_id is not None


def test_connected_resets_session_on_mismatch():
    node = _make_node()
    with (
        patch.object(node, "make_request", side_effect=NodeAPIError(403, "Session ID mismatch.")),
        patch.object(node, "_reset_local_state") as reset,
    ):
        assert node.connected is False
        reset.assert_called_once()


def test_try_restore_reattaches_when_session_and_core_alive():
    node = _make_node()

    def fake_request(path, timeout, **params):
        if path == "/ping":
            return {}
        if path == "/":
            return {"started": True, "core_version": "1.8.0"}
        raise AssertionError(path)

    with (
        patch.object(node, "make_request", side_effect=fake_request),
        patch.object(node, "_setup_api") as setup_api,
    ):
        assert node.try_restore() is True
        setup_api.assert_called_once()
        assert node._started is True


def test_try_restore_false_when_core_down():
    node = _make_node()

    def fake_request(path, timeout, **params):
        if path == "/ping":
            return {}
        if path == "/":
            return {"started": False}
        raise AssertionError(path)

    with patch.object(node, "make_request", side_effect=fake_request):
        assert node.try_restore() is False
    assert node._session_id is not None


def test_try_restore_raises_on_transport_error_without_dropping_session():
    node = _make_node()
    with patch.object(node, "make_request", side_effect=NodeAPIError(0, "Connection reset")):
        with pytest.raises(NodeAPIError):
            node.try_restore()
    assert node._session_id is not None


def test_try_restore_false_after_session_mismatch():
    node = _make_node()
    with (
        patch.object(node, "make_request", side_effect=NodeAPIError(403, "Session ID mismatch.")),
        patch.object(node, "_recreate_session"),
    ):
        assert node.try_restore() is False
    assert node._session_id is None


def test_ensure_control_session_does_not_connect_on_blip():
    node = _make_node()
    with (
        patch.object(node, "make_request", side_effect=NodeAPIError(0, "timed out")),
        patch.object(node, "connect") as connect,
    ):
        with pytest.raises(NodeAPIError):
            node._ensure_control_session()
        connect.assert_not_called()
    assert node._session_id is not None


def test_ensure_control_session_connects_on_mismatch():
    node = _make_node()

    with (
        patch.object(node, "make_request", side_effect=NodeAPIError(403, "Session ID mismatch.")),
        patch.object(node, "_reset_local_state"),
        patch.object(node, "connect") as connect,
    ):
        node._ensure_control_session()
        connect.assert_called_once()
