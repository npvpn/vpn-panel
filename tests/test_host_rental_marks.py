"""Отметка аренды живёт на привязке хоста к боту (NPVPN-2044).

На хосте её держать нельзя: один хост может быть отдан нескольким ботам,
и «когда и как его взяли» — свойство пары, а не хоста.
"""

from __future__ import annotations

import sys
import types
from datetime import datetime

# Заглушки app.* снимаются на время импорта и возвращаются обратно — см.
# объяснение в tests/test_update_hosts_upsert.py.
_saved_stubs: dict[str, types.ModuleType] = {}
for _name, _module in list(sys.modules.items()):
    if _name.startswith("app.") and not hasattr(_module, "__file__") and not hasattr(_module, "__path__"):
        _saved_stubs[_name] = sys.modules.pop(_name)

_share_stub = types.ModuleType("app.subscription.share")
_share_stub.generate_v2ray_links = lambda *args, **kwargs: []
sys.modules.setdefault("app.subscription.share", _share_stub)

import pytest  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db import crud  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.models import Bot, ProxyHost, ProxyInbound, host_bot_association  # noqa: E402
from app.models.proxy import ProxyHost as ProxyHostSchema  # noqa: E402

if sys.modules.get("app.subscription.share") is _share_stub:
    del sys.modules["app.subscription.share"]

sys.modules.update(_saved_stubs)

TAG = "VLESS TCP REALITY"


def test_association_has_rental_columns():
    columns = host_bot_association.columns
    assert "rented_at" in columns
    assert columns["rented_at"].nullable is True


def test_source_defaults_to_manual():
    """Дефолт manual: все существующие привязки сделаны руками, и объявлять их
    самообслуживанием значило бы начислить аренду за то, что мы отдали сами."""
    column = host_bot_association.columns["source"]
    assert column.nullable is False
    assert "manual" in str(column.server_default.arg)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _enable_sqlite_fk(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_upsert_preserves_rental_mark(db):
    """Сохранение формы хостов не должно сбрасывать отметку аренды —
    ровно то, из-за чего Task 3 переводил update_hosts на upsert."""
    inbound = ProxyInbound(tag=TAG)
    bot = Bot(username="AppleGurruBot")
    db.add_all([inbound, bot])
    db.flush()
    host = ProxyHost(remark="Нидерланды", address="1.1.1.1", inbound=inbound, bots=[bot])
    db.add(host)
    db.commit()

    db.execute(
        host_bot_association.update()
        .where(host_bot_association.c.host_id == host.id)
        .values(rented_at=datetime(2026, 10, 1), source="self_service")
    )
    db.commit()

    crud.update_hosts(
        db,
        TAG,
        [ProxyHostSchema(id=host.id, remark="Нидерланды", address="1.1.1.1", bot_usernames=["AppleGurruBot"])],
    )

    row = db.execute(host_bot_association.select().where(host_bot_association.c.host_id == host.id)).one()
    assert row.source == "self_service"
    assert row.rented_at == datetime(2026, 10, 1)


def test_unbinding_a_bot_does_not_touch_other_bots_marks(db):
    """Отвязка одного бота не должна пересоздавать привязки остальных:
    иначе отметка аренды у соседа обнулится, а счёт за период уедет."""
    inbound = ProxyInbound(tag=TAG)
    kept = Bot(username="AppleGurruBot")
    removed = Bot(username="vpnZabBot")
    db.add_all([inbound, kept, removed])
    db.flush()
    host = ProxyHost(remark="Нидерланды", address="1.1.1.1", inbound=inbound, bots=[kept, removed])
    db.add(host)
    db.commit()

    db.execute(
        host_bot_association.update()
        .where(host_bot_association.c.bot_id == kept.id)
        .values(rented_at=datetime(2026, 10, 1), source="self_service")
    )
    db.commit()

    crud.update_hosts(
        db,
        TAG,
        [ProxyHostSchema(id=host.id, remark="Нидерланды", address="1.1.1.1", bot_usernames=["AppleGurruBot"])],
    )

    rows = db.execute(host_bot_association.select()).all()
    assert len(rows) == 1
    assert rows[0].source == "self_service"
    assert rows[0].rented_at == datetime(2026, 10, 1)
