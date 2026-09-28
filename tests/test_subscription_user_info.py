"""Заголовок subscription-userinfo всегда отдаёт обычный трафик, не БС."""

from __future__ import annotations

import sys
import types

for _name, _module in list(sys.modules.items()):
    if _name.startswith("app.") and not hasattr(_module, "__file__") and not hasattr(_module, "__path__"):
        del sys.modules[_name]

_share_stub = types.ModuleType("app.subscription.share")
_share_stub.generate_v2ray_links = lambda *args, **kwargs: []
sys.modules.setdefault("app.subscription.share", _share_stub)

from app.subscription.user_info import get_subscription_user_info  # noqa: E402

if sys.modules.get("app.subscription.share") is _share_stub:
    del sys.modules["app.subscription.share"]


def test_subscription_user_info_uses_regular_traffic():
    user = types.SimpleNamespace(used_traffic=50, data_limit=1000, expire=123)

    info = get_subscription_user_info(user)

    assert info == {"upload": 0, "download": 50, "total": 1000, "expire": 123}


def test_subscription_user_info_total_is_zero_without_data_limit():
    user = types.SimpleNamespace(used_traffic=50, data_limit=None, expire=0)

    info = get_subscription_user_info(user)

    assert info["download"] == 50
    assert info["total"] == 0
