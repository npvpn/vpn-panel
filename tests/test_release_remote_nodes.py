"""Panel shutdown must leave remote REST Xray cores running."""

import sys
import types
from unittest.mock import MagicMock, patch

for _name, _module in list(sys.modules.items()):
    if _name.startswith("app.") and not hasattr(_module, "__file__") and not hasattr(_module, "__path__"):
        del sys.modules[_name]

_share_stub = types.ModuleType("app.subscription.share")
_share_stub.generate_v2ray_links = lambda *args, **kwargs: []
sys.modules.setdefault("app.subscription.share", _share_stub)

from app.xray import operations  # noqa: E402

if sys.modules.get("app.subscription.share") is _share_stub:
    del sys.modules["app.subscription.share"]


def test_release_remote_nodes_does_not_disconnect():
    rest = MagicMock()
    rpyc = MagicMock(spec=["disconnect"])
    with patch.object(operations, "xray") as xray_mod:
        xray_mod.nodes = {1: rest, 2: rpyc}
        operations.release_remote_nodes()
    rest.release_local.assert_called_once()
    rest.disconnect.assert_not_called()
    rpyc.disconnect.assert_not_called()
