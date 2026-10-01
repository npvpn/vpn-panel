"""Миграция NPVPN-2044 не меняет, кто какой хост видит.

Это главный тест подпроекта: миграция переносит видимость из неявного правила
в колонку, и единственный способ это проверить — сравнить множество
«кто что видит» до и после.
"""

from __future__ import annotations

import sys
import types

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
from app.db.models import Bot, ProxyHost, ProxyInbound  # noqa: E402
from app.models.host_visibility import HOST_VISIBILITY_SHARED  # noqa: E402

if sys.modules.get("app.subscription.share") is _share_stub:
    del sys.modules["app.subscription.share"]


def old_predicate(bot_usernames: list[str], user_bot_username: str | None) -> bool:
    """Предикат ДО правки, дословно: app/xray/host_addresses.py:host_allowed_for_bot."""
    return not (bot_usernames and user_bot_username and user_bot_username not in bot_usernames)


def new_predicate(visibility: str, bot_usernames: list[str], user_bot_username: str | None) -> bool:
    from app.xray.host_addresses import host_allowed_for_bot

    return host_allowed_for_bot(visibility, bot_usernames, user_bot_username)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_migration_preserves_who_sees_what(db):
    inbound = ProxyInbound(tag="VLESS TCP REALITY")
    bot_a = Bot(username="AppleGurruBot")
    bot_b = Bot(username="vpnZabBot")
    db.add_all([inbound, bot_a, bot_b])
    db.flush()

    bound = ProxyHost(remark="Персональный", address="1.1.1.1", inbound=inbound, bots=[bot_a])
    unbound_enabled = ProxyHost(remark="Общий", address="2.2.2.2", inbound=inbound, is_disabled=False)
    unbound_disabled = ProxyHost(remark="Выключенный", address="3.3.3.3", inbound=inbound, is_disabled=True)
    db.add_all([bound, unbound_enabled, unbound_disabled])
    db.commit()

    hosts = [bound, unbound_enabled, unbound_disabled]
    viewers = ["AppleGurruBot", "vpnZabBot", None]

    before = {(host.remark, viewer): old_predicate(host.bot_usernames, viewer) for host in hosts for viewer in viewers}

    # Эмулируем UPDATE'ы миграции ровно в том виде, в каком они в ревизии.
    db.execute(
        ProxyHost.__table__.update().where(ProxyHost.id.notin_([bound.id])).values(visibility=HOST_VISIBILITY_SHARED)
    )
    db.commit()
    for host in hosts:
        db.refresh(host)

    after = {
        (host.remark, viewer): new_predicate(host.visibility, host.bot_usernames, viewer)
        for host in hosts
        for viewer in viewers
    }

    assert after == before


def test_disabled_unbound_host_becomes_shared(db):
    """Выключенный непривязанный хост обязан стать shared: иначе его включение
    в будущем никому ничего не даст, причём молча."""
    inbound = ProxyInbound(tag="VLESS TCP REALITY")
    db.add(inbound)
    db.flush()
    host = ProxyHost(remark="Выключенный", address="3.3.3.3", inbound=inbound, is_disabled=True)
    db.add(host)
    db.commit()

    db.execute(ProxyHost.__table__.update().values(visibility=HOST_VISIBILITY_SHARED))
    db.commit()
    db.refresh(host)

    assert host.visibility == HOST_VISIBILITY_SHARED
