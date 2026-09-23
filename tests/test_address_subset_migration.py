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


def test_user_has_rotation_offset_timestamp():
    """C1 (финальное ревью, NPVPN-2072): без метки момента последней ротации
    журнал не может отличить "offset всегда был таким" от "offset менялся" —
    см. app/services/address_history.py:reconstruct."""
    column = User.__table__.columns["address_rotation_offset_at"]
    assert column.nullable is True


def test_weight_snapshot_is_unique_per_epoch_and_node():
    constraints = {
        tuple(sorted(col.name for col in constraint.columns))
        for constraint in NodeWeightSnapshot.__table__.constraints
        if hasattr(constraint, "columns") and len(constraint.columns) == 2
    }
    assert ("epoch_index", "node_id") in constraints


def test_weight_snapshot_node_id_has_no_fk():
    """I3 (финальное ревью, NPVPN-2072): архив журнала обязан пережить
    удаление ноды. Раньше node_id был FK с CASCADE — удаление Node стирало
    веса вместе с ней, и reconstruct задним числом подставлял бы МЕДИАНУ
    вместо реального веса (weighted_candidates), выдавая уверенный неверный
    ответ. Теперь node_id — обычная колонка без ссылочной целостности."""
    assert not NodeWeightSnapshot.__table__.columns["node_id"].foreign_keys


def test_host_has_per_host_subset_columns():
    """NPVPN-2072: настройки сужения живут на хосте, а не на боте."""
    from app.db.models import ProxyHost

    columns = ProxyHost.__table__.columns
    assert "address_subset_enabled" in columns
    assert "address_subset_size" in columns
    assert "address_rotation_days" in columns
    # Выключено по умолчанию: включение меняет выдачу адресов всем юзерам хоста сразу.
    assert columns["address_subset_enabled"].nullable is False
    assert columns["address_subset_enabled"].server_default is not None
    # size/период не заданы — «отдавать все адреса», а не «отдавать один».
    assert columns["address_subset_size"].nullable is True
    assert columns["address_rotation_days"].nullable is True


def test_bot_settings_no_longer_carry_subset_keys():
    """Ключи уехали из синка настроек: приёмник панели их больше не знает (NPVPN-2072)."""
    from app.models.bot import BotSettingsPayload
    from app.services.managed_settings import BOT_MANAGED_JSON_FIELDS

    for key in ("sub_address_subset_enabled", "sub_address_subset_size", "sub_address_rotation_days"):
        assert key not in BOT_MANAGED_JSON_FIELDS
        assert key not in BotSettingsPayload.model_fields
