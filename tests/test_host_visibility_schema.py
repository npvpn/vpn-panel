"""Схема NPVPN-2044: видимость хоста живёт в колонке, а не в пустой привязке."""

from __future__ import annotations

import sys
import types

import pytest
from pydantic import ValidationError

# app/__init__.py тяжёлый, а app.db.models тянет app.models.user →
# app.subscription.share, который на импорте лезет в сеть за public ip.
# Тот же обход, что в tests/test_record_bs_usage.py и test_address_subset_migration.py.
for _name, _module in list(sys.modules.items()):
    if _name.startswith("app.") and not hasattr(_module, "__file__") and not hasattr(_module, "__path__"):
        del sys.modules[_name]

_share_stub = types.ModuleType("app.subscription.share")
_share_stub.generate_v2ray_links = lambda *args, **kwargs: []
sys.modules.setdefault("app.subscription.share", _share_stub)

from app.db.models import HOST_VISIBILITY_RESTRICTED, ProxyHost  # noqa: E402
from app.models.proxy import ProxyHost as ProxyHostSchema  # noqa: E402

if sys.modules.get("app.subscription.share") is _share_stub:
    del sys.modules["app.subscription.share"]


def test_host_has_visibility_column_defaulting_to_restricted():
    """Дефолт restricted охраняет цель задачи: новый хост не уходит всем партнёрам молча."""
    column = ProxyHost.__table__.columns["visibility"]
    assert column.nullable is False
    assert HOST_VISIBILITY_RESTRICTED in str(column.server_default.arg)


def _host(**overrides) -> dict:
    payload = {"remark": "Нидерланды", "address": "1.2.3.4"}
    payload.update(overrides)
    return payload


def test_visibility_rejects_unknown_value():
    """Опечатка в значении не должна молча превратиться в «виден всем»:
    предикат сравнивает с литералом "shared", всё прочее читается как restricted."""
    with pytest.raises(ValidationError):
        ProxyHostSchema(**_host(visibility="public"))


def test_visibility_accepts_shared_and_restricted():
    assert ProxyHostSchema(**_host(visibility="shared")).visibility == "shared"
    assert ProxyHostSchema(**_host(visibility="restricted")).visibility == "restricted"
