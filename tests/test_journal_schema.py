"""Схема NPVPN-2072 (журнал снимков и закреплений нод) присутствует в моделях."""

from __future__ import annotations

import sys
import types

# app/__init__.py тяжёлый, а app.subscription.share тянет за собой весь стек
# генерации ссылок — тот же обход, что в test_address_subset_migration.py.
for _name, _module in list(sys.modules.items()):
    if _name.startswith("app.") and not hasattr(_module, "__file__") and not hasattr(_module, "__path__"):
        del sys.modules[_name]

_share_stub = types.ModuleType("app.subscription.share")
_share_stub.generate_v2ray_links = lambda *args, **kwargs: []
sys.modules.setdefault("app.subscription.share", _share_stub)

from app.db.models import HostCompositionSnapshot, UserNodePin  # noqa: E402

if sys.modules.get("app.subscription.share") is _share_stub:
    del sys.modules["app.subscription.share"]


def test_composition_snapshot_unique_per_epoch_and_host():
    constraints = {
        tuple(sorted(c.name for c in constraint.columns))
        for constraint in HostCompositionSnapshot.__table__.constraints
        if hasattr(constraint, "columns") and len(constraint.columns) == 2
    }
    assert ("epoch_index", "host_id") in constraints


def test_composition_snapshot_cascades_from_host():
    fk = next(iter(HostCompositionSnapshot.__table__.columns["host_id"].foreign_keys))
    assert fk.ondelete == "CASCADE"


def test_pin_has_expiry_and_author():
    cols = UserNodePin.__table__.columns
    assert cols["expires_at"].nullable is False
    assert "created_by" in cols
    assert "note" in cols


def test_pin_cascades_from_user_and_host():
    for column in ("user_id", "host_id"):
        fk = next(iter(UserNodePin.__table__.columns[column].foreign_keys))
        assert fk.ondelete == "CASCADE", column
