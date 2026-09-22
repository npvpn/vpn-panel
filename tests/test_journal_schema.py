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

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.models import HostCompositionSnapshot, UserNodePin  # noqa: E402

if sys.modules.get("app.subscription.share") is _share_stub:
    del sys.modules["app.subscription.share"]


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_composition_snapshot_unique_per_epoch_and_host():
    constraints = {
        tuple(sorted(c.name for c in constraint.columns))
        for constraint in HostCompositionSnapshot.__table__.constraints
        if hasattr(constraint, "columns") and len(constraint.columns) == 2
    }
    assert ("epoch_index", "host_id") in constraints


def test_composition_snapshot_host_id_has_no_fk():
    """I3 (финальное ревью, NPVPN-2072): архив журнала обязан пережить удаление
    хоста. Раньше host_id был FK с CASCADE — удаление ProxyHost стирало снимки
    состава вместе с ним, и локация молча исчезала из истории без пометки.
    Теперь host_id — обычная колонка без ссылочной целостности: удаление хоста
    не трогает архив, а «висячий» host_id — ожидаемое состояние архивной
    записи, не баг."""
    assert not HostCompositionSnapshot.__table__.columns["host_id"].foreign_keys


def test_composition_snapshot_survives_host_deletion(db):
    """Прямая проверка I3: удалили ProxyHost — снимок состава остался в БД."""
    from app.db.models import ProxyHost, ProxyInbound

    db.add(ProxyInbound(tag="inbound-survives"))
    db.commit()
    host = ProxyHost(remark="to-delete", address="", inbound_tag="inbound-survives")
    db.add(host)
    db.commit()
    db.refresh(host)

    snapshot = HostCompositionSnapshot(epoch_index=1, host_id=host.id, payload=[])
    db.add(snapshot)
    db.commit()

    db.delete(host)
    db.commit()

    survivor = db.query(HostCompositionSnapshot).filter(HostCompositionSnapshot.host_id == host.id).first()
    assert survivor is not None


def test_pin_has_expiry_and_author():
    cols = UserNodePin.__table__.columns
    assert cols["expires_at"].nullable is False
    assert "created_by" in cols
    assert "note" in cols


def test_pin_cascades_from_user_and_host():
    for column in ("user_id", "host_id"):
        fk = next(iter(UserNodePin.__table__.columns[column].foreign_keys))
        assert fk.ondelete == "CASCADE", column
