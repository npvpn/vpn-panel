"""Профиль подписки панели без строки бота (NPVPN-2244)."""

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

from app.db.base import Base  # noqa: E402
from app.db.models import Bot, BotSettings, User  # noqa: E402
from app.models.user import UserStatus  # noqa: E402

if sys.modules.get("app.subscription.share") is _share_stub:
    del sys.modules["app.subscription.share"]

sys.modules.update(_saved_stubs)


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


def test_user_without_bot_reads_panel_subscription_profile(db):
    from app.models.bot import SubscriptionProfilePayload
    from app.services.subscription_profile import save_subscription_profile
    from app.subscription.bot_settings import resolve_bot_settings

    save_subscription_profile(
        db,
        SubscriptionProfilePayload(sub_profile_title="Моя панель", sub_update_interval="6"),
    )
    user = User(username="solo", status=UserStatus.active)
    db.add(user)
    db.commit()

    settings = resolve_bot_settings(user)
    assert settings["sub_profile_title"] == "Моя панель"
    assert settings["sub_update_interval"] == "6"


def test_user_with_bot_ignores_panel_subscription_profile(db):
    from app.models.bot import SubscriptionProfilePayload
    from app.services.subscription_profile import save_subscription_profile
    from app.subscription.bot_settings import resolve_bot_settings

    save_subscription_profile(db, SubscriptionProfilePayload(sub_profile_title="Панель"))
    bot = Bot(username="only")
    db.add(bot)
    db.flush()
    db.add(BotSettings(bot_id=bot.id, data={"sub_profile_title": "Бот"}))
    user = User(username="member", status=UserStatus.active, bot=bot)
    db.add(user)
    db.commit()

    assert resolve_bot_settings(user)["sub_profile_title"] == "Бот"


def test_unassigned_user_uses_default_settings_when_a_bot_exists(db):
    from app.models.bot import SubscriptionProfilePayload, apply_bot_settings_fallback
    from app.services.subscription_profile import save_subscription_profile
    from app.subscription.bot_settings import resolve_bot_settings

    save_subscription_profile(db, SubscriptionProfilePayload(sub_profile_title="Панель"))
    db.add(Bot(username="only"))
    user = User(username="unassigned", status=UserStatus.active)
    db.add(user)
    db.commit()

    assert resolve_bot_settings(user)["sub_profile_title"] == apply_bot_settings_fallback(None)["sub_profile_title"]


def test_creating_first_bot_invalidates_solo_profile_cache(db):
    from app.db import crud
    from app.models.bot import SubscriptionProfilePayload, apply_bot_settings_fallback
    from app.services.subscription_profile import save_subscription_profile
    from app.subscription.bot_settings import resolve_bot_settings

    save_subscription_profile(db, SubscriptionProfilePayload(sub_profile_title="Панель"))
    user = User(username="transition", status=UserStatus.active)
    db.add(user)
    db.commit()

    assert resolve_bot_settings(user)["sub_profile_title"] == "Панель"
    crud.create_bot(db, "only")
    assert resolve_bot_settings(user)["sub_profile_title"] == apply_bot_settings_fallback(None)["sub_profile_title"]


def test_profile_roundtrip_keeps_only_subscription_fields(db):
    from app.models.bot import SubscriptionProfilePayload
    from app.services.subscription_profile import get_subscription_profile, save_subscription_profile

    save_subscription_profile(
        db,
        SubscriptionProfilePayload(sub_profile_title="Моя панель", show_ads=False, web_url="https://vpn.example"),
    )
    stored = get_subscription_profile(db)
    assert stored["sub_profile_title"] == "Моя панель"
    assert stored["show_ads"] is False
    assert stored["web_url"] == "https://vpn.example"
    assert "bot_url" not in stored
    assert "sub_device_limit_hard_mode" not in stored


def test_profile_does_not_override_panel_hard_mode(db):
    from app.models.bot import SubscriptionProfilePayload
    from app.models.settings import PanelSettingsPayload
    from app.services.panel_settings import save_panel_settings
    from app.services.subscription_profile import get_subscription_profile, save_subscription_profile
    from app.subscription.bot_settings import resolve_bot_settings

    save_panel_settings(db, PanelSettingsPayload(sub_device_limit_hard_mode=True))
    save_subscription_profile(db, SubscriptionProfilePayload(sub_profile_title="Панель"))
    user = User(username="solo", status=UserStatus.active)
    db.add(user)
    db.commit()

    assert get_subscription_profile(db)["sub_profile_title"] == "Панель"
    assert resolve_bot_settings(user)["sub_device_limit_hard_mode"] is True


def test_users_without_bots_share_one_profile_query_per_session(db):
    from app.models.bot import SubscriptionProfilePayload
    from app.services.subscription_profile import save_subscription_profile
    from app.subscription.bot_settings import resolve_bot_settings

    save_subscription_profile(db, SubscriptionProfilePayload(sub_profile_title="Один профиль"))
    users = [User(username=f"solo-{i}", status=UserStatus.active) for i in range(3)]
    db.add_all(users)
    db.commit()
    db.info.clear()
    queries = []

    def count_profile_query(_conn, _cursor, statement, _parameters, _context, _executemany):
        if "global_settings" in statement and "SELECT" in statement:
            queries.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", count_profile_query)
    try:
        assert [resolve_bot_settings(user)["sub_profile_title"] for user in users] == ["Один профиль"] * 3
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", count_profile_query)

    assert len(queries) == 2  # профиль и настройки панели, каждый читается один раз
