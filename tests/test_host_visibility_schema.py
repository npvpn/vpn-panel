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


def test_host_has_sellable_and_price_columns():
    assert ProxyHost.__table__.columns["is_sellable"].nullable is False
    assert ProxyHost.__table__.columns["catalog_price"].nullable is True


def _host(**overrides) -> dict:
    payload = {"remark": "Нидерланды", "address": "1.2.3.4"}
    payload.update(overrides)
    return payload


def test_catalog_price_rejects_negative():
    with pytest.raises(ValidationError):
        ProxyHostSchema(**_host(catalog_price="-1.00"))


def test_catalog_price_rejects_three_decimals():
    """Иначе счёт подпроекта 2 молча округлит цену, и партнёр увидит не ту сумму."""
    with pytest.raises(ValidationError):
        ProxyHostSchema(**_host(catalog_price="10.001"))


def test_sellable_shared_host_is_rejected():
    """shared-хост и так достаётся всем бесплатно — продавать его нечем,
    а каталог подпроекта 3 показал бы товар, который уже отдан."""
    with pytest.raises(ValidationError):
        ProxyHostSchema(**_host(visibility="shared", is_sellable=True))


def test_restricted_sellable_host_is_accepted():
    host = ProxyHostSchema(**_host(visibility="restricted", is_sellable=True, catalog_price="890.00"))
    assert host.is_sellable is True
