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

# Other test modules import real xray_api.types during collection. The local
# stub is only needed while importing node.py and must not leak to them.
if sys.modules.get("xray_api") is _stubs["xray_api"]:
    del sys.modules["xray_api"]


def _make_node() -> ReSTXRayNode:
    node = ReSTXRayNode.__new__(ReSTXRayNode)
    node.address = "10.0.0.1"
    node.port = 62050
    node.api_port = 62051
    node._session_id = "11111111-1111-1111-1111-111111111111"
    node._node_cert = "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"
    node._node_certfile = MagicMock()
    node._certfile = MagicMock()
    node._keyfile = MagicMock()
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


def test_try_restore_fetches_cert_when_session_has_no_cached_cert():
    node = _make_node()
    node._node_cert = None
    node._node_certfile = None

    def fake_request(path, timeout, **params):
        if path == "/ping":
            return {}
        if path == "/":
            return {"started": True, "core_version": "1.8.0"}
        raise AssertionError(path)

    with (
        patch("app.xray.node.fetch_server_certificate", return_value="CERT") as fetch,
        patch("app.xray.node.string_to_temp_file", return_value=MagicMock(name="certfile")) as tmp,
        patch.object(node, "make_request", side_effect=fake_request),
        patch.object(node, "_setup_api"),
        patch.object(node, "connect") as connect,
    ):
        assert node.try_restore() is True

    args, _kwargs = fetch.call_args
    assert args[0] == "10.0.0.1"
    assert args[1] == 62050
    assert isinstance(args[2], int)
    tmp.assert_called_once_with("CERT")
    connect.assert_not_called()
    assert node._session_id == "11111111-1111-1111-1111-111111111111"


def test_try_restore_raises_when_cert_fetch_fails_and_keeps_session():
    node = _make_node()
    node._node_cert = None
    node._node_certfile = None

    with (
        patch("app.xray.node.fetch_server_certificate", side_effect=ConnectionError("timed out")),
        patch.object(node, "connect") as connect,
        patch.object(node, "make_request") as request,
    ):
        with pytest.raises(ConnectionError, match="timed out"):
            node.try_restore()

    connect.assert_not_called()
    request.assert_not_called()
    assert node._session_id == "11111111-1111-1111-1111-111111111111"


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


def test_make_request_uses_full_timeout_for_body_upload():
    """urllib3 1.x applies connect-half while writing the body — do not cap at 10s."""
    node = _make_node()
    node._rest_api_url = "https://10.0.0.1:62050"
    node._session_id = "sess"
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.return_value = {"ok": True}
    node.session = MagicMock()
    node.session.post.return_value = mock_res

    assert node.make_request("/restart", timeout=90, config="{}") == {"ok": True}
    _, kwargs = node.session.post.call_args
    assert kwargs["timeout"] == 90


def test_connect_publishes_new_session_and_release_local_does_not():
    node = _make_node()
    node._session_id = None
    seen = []
    node.set_control_session_listener(seen.append)

    with (
        patch("app.xray.node.fetch_server_certificate", return_value="CERT"),
        patch("app.xray.node.string_to_temp_file", return_value=MagicMock(name="certfile")),
        patch.object(node, "make_request", return_value={"session_id": "22222222-2222-2222-2222-222222222222"}),
    ):
        node.connect()

    assert seen == ["22222222-2222-2222-2222-222222222222"]
    node.release_local()
    assert seen == ["22222222-2222-2222-2222-222222222222"]


def test_disconnect_publishes_clear_only_after_remote_success():
    node = _make_node()
    seen = []
    node.set_control_session_listener(seen.append)

    with patch.object(node, "make_request", return_value={"connected": False}):
        node.disconnect()
    assert seen == [None]

    node._session_id = "11111111-1111-1111-1111-111111111111"
    with patch.object(node, "make_request", side_effect=NodeAPIError(0, "timed out")):
        node.disconnect()
    assert seen == [None]


def test_connect_clears_previous_session_after_successful_disconnect_even_if_new_connect_fails():
    node = _make_node()
    seen = []
    node.set_control_session_listener(seen.append)

    def request(path, timeout):
        if path == "/disconnect":
            return {"connected": False}
        raise NodeAPIError(0, "connect failed")

    with (
        patch("app.xray.node.fetch_server_certificate", return_value="CERT"),
        patch("app.xray.node.string_to_temp_file", return_value=MagicMock(name="certfile")),
        patch.object(node, "make_request", side_effect=request),
        pytest.raises(NodeAPIError, match="connect failed"),
    ):
        node.connect()

    assert seen == [None]


def test_release_local_closes_http_without_remote_disconnect():
    node = _make_node()
    with patch.object(node, "make_request") as request:
        node.release_local()

    node.session.close.assert_called_once()
    request.assert_not_called()
