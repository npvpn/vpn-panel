"""Перед вторым ботом хосты соло-панели остаются у первого (NPVPN-2244)."""

from __future__ import annotations

import sys
import threading
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
from app.db.models import Bot, ProxyHost, ProxyInbound, User, host_bot_association  # noqa: E402

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


def test_first_bot_is_assigned_to_existing_users(db):
    users = [User(username="first_user"), User(username="second_user")]
    db.add_all(users)
    db.commit()

    first = crud.create_bot(db, "first")

    assert {user.bot_id for user in db.query(User).all()} == {first.id}


def test_first_managed_bot_is_assigned_to_existing_users(db):
    from app.services import managed_settings as svc

    users = [User(username="first_user"), User(username="second_user")]
    db.add_all(users)
    db.commit()

    svc.apply_managed_bot_push(db, svc.BOT_SETTINGS_KEY, 42, data=_MANAGED, version="v1", source="telegram")

    first = db.query(Bot).one()
    assert {user.bot_id for user in db.query(User).all()} == {first.id}


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


def test_parallel_managed_creation_binds_hosts_to_the_first_service(tmp_path):
    from app.services import managed_settings as svc

    engine = create_engine(
        f"sqlite:///{tmp_path / 'solo.db'}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        inbound = ProxyInbound(tag="VLESS")
        session.add(inbound)
        session.flush()
        session.add(ProxyHost(remark="Свободный", address="1.1.1.1", inbound=inbound))
        session.commit()

    errors: list[BaseException] = []
    barrier = threading.Barrier(2)

    def push(source_id: int, username: str) -> None:
        payload = {**_MANAGED, "username": username, "bot_url": f"https://t.me/{username}"}
        try:
            barrier.wait(timeout=5)
            with Session(engine) as session:
                svc.apply_managed_bot_push(
                    session,
                    svc.BOT_SETTINGS_KEY,
                    source_id,
                    data=payload,
                    version="v1",
                    source="telegram",
                )
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=push, args=(1, "alpha_bot")),
        threading.Thread(target=push, args=(2, "beta_bot")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    assert all(not thread.is_alive() for thread in threads)
    with Session(engine) as session:
        bots = session.query(Bot).order_by(Bot.id).all()
        assert {bot.username for bot in bots} == {"alpha_bot", "beta_bot"}
        assert {item.remark for item in bots[0].hosts} == {"Свободный"}
        assert list(bots[1].hosts) == []


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


class _LockResult:
    def scalar(self):
        return 1


class _MySQLLockConnection:
    def __init__(self, events: list[str]):
        self.events = events

    def execute(self, statement):
        query = str(statement)
        self.events.append("release" if "RELEASE_LOCK" in query else "acquire")
        return _LockResult()

    def close(self):
        self.events.append("close")


class _MySQLLockDB:
    bind = types.SimpleNamespace(dialect=types.SimpleNamespace(name="mysql"))

    def __init__(self, events: list[str]):
        self.events = events
        self.connection = _MySQLLockConnection(events)
        self.engine = self

    def get_bind(self):
        return self

    def connect(self):
        self.events.append("connect")
        return self.connection


def test_mysql_creation_lock_stays_open_until_work_is_complete():
    events: list[str] = []
    db = _MySQLLockDB(events)

    with crud._lock_bot_creation(db):
        events.append("commit")
        assert events == ["connect", "acquire", "commit"]

    assert events == ["connect", "acquire", "commit", "release", "close"]


def test_mysql_creation_lock_is_released_when_work_fails():
    events: list[str] = []
    db = _MySQLLockDB(events)

    with pytest.raises(RuntimeError, match="commit failed"):
        with crud._lock_bot_creation(db):
            events.append("commit")
            raise RuntimeError("commit failed")

    assert events == ["connect", "acquire", "commit", "release", "close"]
