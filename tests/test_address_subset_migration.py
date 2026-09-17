"""Схема NPVPN-2072 присутствует в моделях и согласована с ожиданиями кода."""

from __future__ import annotations

import sys
import types

# app/__init__.py тяжёлый, а app.subscription.share тянет за собой весь стек
# генерации ссылок — тот же обход, что в test_hosting_traffic_limit.py и
# test_expire_bigint_migration.py.
for _name, _module in list(sys.modules.items()):
    if _name.startswith("app.") and not hasattr(_module, "__file__") and not hasattr(_module, "__path__"):
        del sys.modules[_name]

_share_stub = types.ModuleType("app.subscription.share")
_share_stub.generate_v2ray_links = lambda *args, **kwargs: []
sys.modules.setdefault("app.subscription.share", _share_stub)

from app.db.models import Node, NodeWeightSnapshot, User  # noqa: E402

if sys.modules.get("app.subscription.share") is _share_stub:
    del sys.modules["app.subscription.share"]


def test_node_has_hosting_used_columns():
    assert "hosting_used_bytes" in Node.__table__.columns
    assert "hosting_used_at" in Node.__table__.columns
    assert Node.__table__.columns["hosting_used_bytes"].nullable is True


def test_user_has_rotation_offset_with_default():
    column = User.__table__.columns["address_rotation_offset"]
    assert column.nullable is False
    assert column.server_default is not None


def test_weight_snapshot_is_unique_per_epoch_and_node():
    constraints = {
        tuple(sorted(col.name for col in constraint.columns))
        for constraint in NodeWeightSnapshot.__table__.constraints
        if hasattr(constraint, "columns") and len(constraint.columns) == 2
    }
    assert ("epoch_index", "node_id") in constraints


def test_weight_snapshot_cascades_from_node():
    fk = next(iter(NodeWeightSnapshot.__table__.columns["node_id"].foreign_keys))
    assert fk.ondelete == "CASCADE"
