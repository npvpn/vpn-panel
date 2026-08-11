import sys
import types

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Model imports reach app.subscription.share through app.models.user. The test
# only needs the bot tables, so avoid loading subscription rendering machinery.
_share_stub = types.ModuleType("app.subscription.share")
_share_stub.generate_v2ray_links = lambda *args, **kwargs: []
sys.modules.setdefault("app.subscription.share", _share_stub)

from app.db.base import Base
from app.db.models import Bot, BotSettings, ManagedSetting
from app.models.bot import apply_bot_settings_fallback
from app.services import managed_settings as svc

MANAGED_DATA = {
    "username": "synced_bot",
    "title": "Synced bot",
    "bot_url": "https://t.me/synced_bot",
    "web_url": "panel.example.com",
    "sub_support_url": "https://t.me/support",
    "sub_subscription_domain": "sub.example.com",
}


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[Bot.__table__, BotSettings.__table__, ManagedSetting.__table__])
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_first_push_binds_by_username_and_preserves_panel_only_settings(db):
    bot = Bot(username="synced_bot", admin_sync_enabled=True)
    db.add(bot)
    db.flush()
    db.add(BotSettings(bot_id=bot.id, data={"show_ads": False, "panel_only": {"keep": True}}))
    db.commit()

    state = svc.apply_managed_bot_push(
        db,
        svc.BOT_SETTINGS_KEY,
        42,
        data=MANAGED_DATA,
        version="v1",
        source="telegram",
    )

    db.refresh(bot)
    settings = db.query(BotSettings).filter(BotSettings.bot_id == bot.id).one().data
    assert bot.source_bot_id == 42
    assert bot.title == "Synced bot"
    assert settings["web_url"] == "https://panel.example.com"
    assert settings["panel_only"] == {"keep": True}
    assert settings["show_ads"] is False
    assert state["key"] == "bot_settings:42"
    assert state["version"] == "v1"


def test_first_push_creates_enabled_bot_and_later_uses_stable_source_id(db):
    svc.apply_managed_bot_push(
        db,
        svc.BOT_SETTINGS_KEY,
        73,
        data=MANAGED_DATA,
        version="v1",
        source="telegram",
    )
    changed = {**MANAGED_DATA, "username": "renamed_bot", "title": None}
    svc.apply_managed_bot_push(
        db,
        svc.BOT_SETTINGS_KEY,
        73,
        data=changed,
        version="v2",
        source="telegram",
    )

    bots = db.query(Bot).all()
    assert len(bots) == 1
    assert bots[0].username == "renamed_bot"
    assert bots[0].admin_sync_enabled is True


def test_disabled_existing_bot_rejects_push(db):
    db.add(Bot(username="synced_bot", admin_sync_enabled=False))
    db.commit()

    with pytest.raises(svc.AdminSyncDisabledError):
        svc.apply_managed_bot_push(
            db,
            svc.BOT_SETTINGS_KEY,
            42,
            data=MANAGED_DATA,
            version="v1",
            source="telegram",
        )


def test_disabling_unlinks_state_without_changing_values(db):
    svc.apply_managed_bot_push(
        db,
        svc.BOT_SETTINGS_KEY,
        42,
        data=MANAGED_DATA,
        version="v1",
        source="telegram",
    )
    bot = db.query(Bot).filter(Bot.source_bot_id == 42).one()
    before = dict(db.query(BotSettings).filter(BotSettings.bot_id == bot.id).one().data)

    svc.set_bot_admin_sync(db, bot, False)

    assert svc.read_bot_managed_state(db, bot) is None
    assert db.query(BotSettings).filter(BotSettings.bot_id == bot.id).one().data == before
    with pytest.raises(svc.AdminSyncDisabledError):
        svc.read_managed_bot_state(db, svc.BOT_SETTINGS_KEY, 42)


def test_manual_full_settings_payload_allows_unchanged_managed_fields_only(db):
    svc.apply_managed_bot_push(
        db,
        svc.BOT_SETTINGS_KEY,
        42,
        data=MANAGED_DATA,
        version="v1",
        source="telegram",
    )
    bot = db.query(Bot).filter(Bot.source_bot_id == 42).one()
    full_payload = apply_bot_settings_fallback(db.query(BotSettings).filter(BotSettings.bot_id == bot.id).one().data)
    full_payload["show_ads"] = False

    svc.ensure_bot_settings_update_allowed(db, bot, full_payload)
    with pytest.raises(svc.ManagedFieldChangeError):
        svc.ensure_bot_settings_update_allowed(
            db,
            bot,
            {**full_payload, "sub_support_url": "https://example.com/other"},
        )


def test_manual_identity_payload_allows_unchanged_managed_fields_only(db):
    svc.apply_managed_bot_push(
        db,
        svc.BOT_SETTINGS_KEY,
        42,
        data=MANAGED_DATA,
        version="v1",
        source="telegram",
    )
    bot = db.query(Bot).filter(Bot.source_bot_id == 42).one()

    svc.ensure_bot_identity_update_allowed(
        db,
        bot,
        username=bot.username,
        title=bot.title,
        web_url="panel.example.com",
    )
    with pytest.raises(svc.ManagedFieldChangeError):
        svc.ensure_bot_identity_update_allowed(
            db,
            bot,
            username="other_bot",
            title=bot.title,
            web_url="panel.example.com",
        )
