"""Заголовок subscription-userinfo: БС-пара только если у бота есть БС-хосты."""

from __future__ import annotations

import sys
import types

for _name, _module in list(sys.modules.items()):
    if _name.startswith("app.") and not hasattr(_module, "__file__") and not hasattr(_module, "__path__"):
        del sys.modules[_name]

_share_stub = types.ModuleType("app.subscription.share")
_share_stub.generate_v2ray_links = lambda *args, **kwargs: []
sys.modules.setdefault("app.subscription.share", _share_stub)

from app.db import crud  # noqa: E402
from app.subscription.user_info import get_subscription_user_info  # noqa: E402

if sys.modules.get("app.subscription.share") is _share_stub:
    del sys.modules["app.subscription.share"]


def _user():
    return types.SimpleNamespace(used_traffic=50, data_limit=1000, expire=123)


def test_regular_bar_when_bot_has_no_bs_hosts(monkeypatch):
    called = []
    monkeypatch.setattr(crud, "normalize_bs_extra_period", lambda *a, **k: called.append("pool") or 0)
    monkeypatch.setattr(crud, "get_bs_usage_totals", lambda *a, **k: called.append("used") or 0)

    info = get_subscription_user_info(
        _user(),
        db=object(),
        panel_settings={"bs_monthly_limit": 3 * 1024**3},
        user_id=1,
        use_bs_bar=False,
    )

    assert info["download"] == 50
    assert info["total"] == 1000
    assert info["expire"] == 123
    assert called == []


def test_bs_bar_when_bot_has_bs_hosts(monkeypatch):
    monkeypatch.setattr(crud, "normalize_bs_extra_period", lambda *a, **k: 2)
    monkeypatch.setattr(crud, "get_bs_usage_totals", lambda *a, **k: 8)

    info = get_subscription_user_info(
        _user(),
        db=object(),
        panel_settings={"bs_monthly_limit": 10},
        user_id=1,
        use_bs_bar=True,
    )

    assert info["download"] == 8
    assert info["total"] == 12
