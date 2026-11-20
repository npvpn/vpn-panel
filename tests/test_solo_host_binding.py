"""Перед вторым ботом хосты соло-панели остаются у первого (NPVPN-2244)."""

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

if sys.modules.get("app.subscription.share") is _share_stub:
    del sys.modules["app.subscription.share"]

sys.modules.update(_saved_stubs)

_MANAGED = {
    "username": "synced_bot",
    "title": "Synced",
    "bot_url": "https://t.me/synced_bot",
    "web_url": "panel.example.com",
    "sub_support_url": "https://t.me/support",
    "sub_subscription_domain": "sub.example.com",
}


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


def _host(session, inbound, remark: str) -> ProxyHost:
    host = ProxyHost(remark=remark, address="1.1.1.1", inbound=inbound)
    session.add(host)
    session.flush()
    return host


def test_second_bot_keeps_every_host_on_the_first(db):
    inbound = ProxyInbound(tag="VLESS")
    first = Bot(username="only")
    db.add_all([inbound, first])
    db.flush()
    kept = _host(db, inbound, "Уже выдан")
    kept.bots = [first]
    free = _host(db, inbound, "Без привязки")
    db.commit()

    crud.create_bot(db, "second")

    first_names = {host.remark for host in db.query(Bot).filter(Bot.username == "only").one().hosts}
    second = db.query(Bot).filter(Bot.username == "second").one()
    assert first_names == {"Уже выдан", "Без привязки"}
    assert second.hosts == []
    rented = {row.host_id: row.rented_at for row in db.execute(host_bot_association.select()).all()}
    assert rented[free.id] is None
    assert rented[kept.id] is None


def test_managed_push_of_second_bot_binds_hosts_to_the_first(db):
    from app.services import managed_settings as svc

    inbound = ProxyInbound(tag="VLESS")
    first = Bot(username="only", admin_sync_enabled=True)
    db.add_all([inbound, first])
    db.flush()
    host = ProxyHost(remark="Свободный", address="1.1.1.1", inbound=inbound)
    db.add(host)
    db.commit()

    svc.apply_managed_bot_push(db, svc.BOT_SETTINGS_KEY, 42, data=_MANAGED, version="v1", source="telegram")

    assert {item.remark for item in db.query(Bot).filter(Bot.username == "only").one().hosts} == {"Свободный"}
    assert db.query(Bot).filter(Bot.username == "synced_bot").one().hosts == []


def test_repeat_managed_push_does_not_bind_again(db):
    from app.services import managed_settings as svc

    inbound = ProxyInbound(tag="VLESS")
    db.add(inbound)
    db.commit()
    svc.apply_managed_bot_push(db, svc.BOT_SETTINGS_KEY, 7, data=_MANAGED, version="v1", source="telegram")
    host = ProxyHost(remark="Позже", address="1.1.1.1", inbound=inbound)
    db.add(host)
    db.commit()
    svc.apply_managed_bot_push(db, svc.BOT_SETTINGS_KEY, 7, data=_MANAGED, version="v2", source="telegram")

    assert db.query(Bot).one().hosts == []
