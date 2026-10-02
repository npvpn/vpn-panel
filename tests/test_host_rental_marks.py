"""Отметка аренды на привязке хоста к боту (NPVPN-2044).

Аренда — свойство пары (хост, бот): один хост может быть отдан нескольким
ботам, и «за что платит этот» — про конкретную пару. Пустая отметка значит
служебную привязку, которая в счёт не идёт.
"""

from __future__ import annotations

import sys
import types

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


def test_association_has_rented_at_and_no_source():
    columns = host_bot_association.columns
    assert "rented_at" in columns
    assert columns["rented_at"].nullable is True
    # source убран: самообслуживания в задаче нет, колонка всегда была бы 'manual'.
    assert "source" not in columns


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


@pytest.fixture
def seeded(db):
    inbound = ProxyInbound(tag=TAG)
    apple = Bot(username="AppleGurruBot")
    zab = Bot(username="vpnZabBot")
    db.add_all([inbound, apple, zab])
    db.flush()
    host = ProxyHost(remark="Нидерланды", address="1.1.1.1", inbound=inbound, bots=[apple, zab])
    db.add(host)
    db.commit()
    return host


def _payload(host, **overrides):
    data = {
        "id": host.id,
        "remark": host.remark,
        "address": host.address,
        "bot_usernames": ["AppleGurruBot", "vpnZabBot"],
    }
    data.update(overrides)
    return ProxyHostSchema(**data)


def _rows(db):
    return {r.bot_id: r.rented_at for r in db.execute(host_bot_association.select()).all()}


def test_rental_mark_is_set_for_listed_bots_only(db, seeded):
    crud.update_hosts(db, TAG, [_payload(seeded, rented_bot_usernames=["AppleGurruBot"])])

    rows = _rows(db)
    marked = [bot_id for bot_id, rented_at in rows.items() if rented_at is not None]
    assert len(marked) == 1
    apple_id = db.query(Bot.id).filter(Bot.username == "AppleGurruBot").scalar()
    assert marked == [apple_id]


def test_rental_mark_is_kept_on_resave(db, seeded):
    """Дата аренды не должна переставляться при каждом сохранении формы:
    иначе «арендует с такого числа» превратится в «арендует с сегодня»."""
    crud.update_hosts(db, TAG, [_payload(seeded, rented_bot_usernames=["AppleGurruBot"])])
    first = [v for v in _rows(db).values() if v is not None][0]

    crud.update_hosts(db, TAG, [_payload(seeded, rented_bot_usernames=["AppleGurruBot"])])
    second = [v for v in _rows(db).values() if v is not None][0]

    assert first == second


def test_rental_mark_is_cleared_when_bot_removed_from_list(db, seeded):
    crud.update_hosts(db, TAG, [_payload(seeded, rented_bot_usernames=["AppleGurruBot"])])
    crud.update_hosts(db, TAG, [_payload(seeded, rented_bot_usernames=[])])

    assert all(rented_at is None for rented_at in _rows(db).values())


def test_rental_for_unbound_bot_is_rejected(db, seeded):
    """Review Focus 1: аренда без доступа бессмысленна, а бот попал бы в счёт,
    не имея хоста."""
    with pytest.raises(ValueError):
        crud.update_hosts(
            db,
            TAG,
            [_payload(seeded, bot_usernames=["AppleGurruBot"], rented_bot_usernames=["vpnZabBot"])],
        )


def test_rented_bot_usernames_is_exposed_on_read(db, seeded):
    crud.update_hosts(db, TAG, [_payload(seeded, rented_bot_usernames=["AppleGurruBot"])])

    db.expire_all()
    host = db.query(ProxyHost).one()
    assert host.rented_bot_usernames == ["AppleGurruBot"]


def test_upsert_preserves_rental_mark_when_other_bot_unbound(db, seeded):
    """Отвязка одного бота не должна сбрасывать отметку у соседа."""
    crud.update_hosts(db, TAG, [_payload(seeded, rented_bot_usernames=["AppleGurruBot"])])
    rented_before = [v for v in _rows(db).values() if v is not None][0]

    crud.update_hosts(
        db,
        TAG,
        [_payload(seeded, bot_usernames=["AppleGurruBot"], rented_bot_usernames=["AppleGurruBot"])],
    )

    rows = _rows(db)
    assert len(rows) == 1
    assert list(rows.values())[0] == rented_before
