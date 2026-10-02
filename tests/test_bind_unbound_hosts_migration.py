"""Миграция NPVPN-2044 не меняет, кто какой хост видит.

Главный тест: правило доступа сменилось с «пустая привязка = всем» на «только
по привязке», и единственный способ убедиться, что ни у кого ничего не пропало —
сравнить множество «кто что видит» до и после.
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
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.models import Bot, ProxyHost, ProxyInbound, host_bot_association  # noqa: E402
from app.xray.host_addresses import host_allowed_for_bot  # noqa: E402

if sys.modules.get("app.subscription.share") is _share_stub:
    del sys.modules["app.subscription.share"]

sys.modules.update(_saved_stubs)


def old_predicate(bot_usernames: list[str], user_bot_username: str | None) -> bool:
    """Предикат ДО правки, дословно."""
    return not (bot_usernames and user_bot_username and user_bot_username not in bot_usernames)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _run_migration(db):
    """Тот же INSERT, что в ревизии d155a50b86b0."""
    unbound = select(ProxyHost.id).where(
        ~select(host_bot_association.c.host_id).where(host_bot_association.c.host_id == ProxyHost.id).exists()
    )
    host_ids = list(db.execute(unbound).scalars())
    bot_ids = list(db.execute(select(Bot.id)).scalars())
    rows = [{"host_id": host_id, "bot_id": bot_id} for host_id in host_ids for bot_id in bot_ids]
    if rows:
        db.execute(host_bot_association.insert(), rows)
    db.commit()


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
    # Только зрители с известным ботом: случай «бот неизвестен» меняется
    # намеренно, см. test_user_without_bot_sees_nothing.
    viewers = ["AppleGurruBot", "vpnZabBot"]
    before = {(host.remark, viewer): old_predicate(host.bot_usernames, viewer) for host in hosts for viewer in viewers}

    _run_migration(db)
    for host in hosts:
        db.refresh(host)

    after = {
        (host.remark, viewer): host_allowed_for_bot(host.bot_usernames, viewer) for host in hosts for viewer in viewers
    }
    assert after == before


def test_disabled_unbound_host_gets_bound(db):
    """Иначе включение такого хоста в будущем никому ничего не даст, причём молча."""
    inbound = ProxyInbound(tag="VLESS TCP REALITY")
    bot = Bot(username="AppleGurruBot")
    db.add_all([inbound, bot])
    db.flush()
    host = ProxyHost(remark="Выключенный", address="3.3.3.3", inbound=inbound, is_disabled=True)
    db.add(host)
    db.commit()

    _run_migration(db)
    db.refresh(host)

    assert host.bot_usernames == ["AppleGurruBot"]


def test_already_bound_host_gets_no_extra_bots(db):
    """Персональный хост не должен расползтись на всех ботов."""
    inbound = ProxyInbound(tag="VLESS TCP REALITY")
    bot_a = Bot(username="AppleGurruBot")
    bot_b = Bot(username="vpnZabBot")
    db.add_all([inbound, bot_a, bot_b])
    db.flush()
    host = ProxyHost(remark="Персональный", address="1.1.1.1", inbound=inbound, bots=[bot_a])
    db.add(host)
    db.commit()

    _run_migration(db)
    db.refresh(host)

    assert host.bot_usernames == ["AppleGurruBot"]


def test_user_without_bot_sees_nothing(db):
    """Намеренное изменение поведения.

    Прежний предикат (`not (bot_usernames and user_bot_username and ...)`)
    отдавал привязанный хост пользователю с `users.bot_id IS NULL`:
    `["bot"] and None` даёт None, `not None` — True. То есть персональный платный
    хост партнёра утекал тому, кто за него не платит. На проде npvpn таких
    пользователей 86, активных 7 (01.10.2026); на opl ни одного.
    """
    assert old_predicate(["AppleGurruBot"], None) is True
    assert host_allowed_for_bot(["AppleGurruBot"], None) is False
