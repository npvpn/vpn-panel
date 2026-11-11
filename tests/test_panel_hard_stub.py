"""Жёсткая заглушка живёт в настройках панели, а не в JSON бота."""

from __future__ import annotations

import sys
import types

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

_share_stub = types.ModuleType("app.subscription.share")
_share_stub.generate_v2ray_links = lambda *args, **kwargs: []
sys.modules.setdefault("app.subscription.share", _share_stub)

from app.db.base import Base  # noqa: E402
from app.db.models import Bot, BotSettings, GlobalSetting, User  # noqa: E402
from app.models.user import UserStatus  # noqa: E402


def _db() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(
        engine,
        tables=[GlobalSetting.__table__, Bot.__table__, BotSettings.__table__, User.__table__],
    )
    return Session(engine)


def test_save_without_hard_mode_keeps_stored_value():
    from app.models.settings import PanelSettingsPayload
    from app.services.panel_settings import save_panel_settings

    with _db() as db:
        save_panel_settings(db, PanelSettingsPayload(sub_device_limit_hard_mode=True))
        saved = save_panel_settings(db, PanelSettingsPayload())
        assert saved["sub_device_limit_hard_mode"] is True


def test_user_with_bot_takes_hard_mode_from_panel_settings():
    from app.models.settings import PanelSettingsPayload
    from app.services.panel_settings import save_panel_settings
    from app.subscription.bot_settings import resolve_bot_settings

    with _db() as db:
        save_panel_settings(db, PanelSettingsPayload(sub_device_limit_hard_mode=True))
        bot = Bot(username="only")
        db.add(bot)
        db.flush()
        db.add(BotSettings(bot_id=bot.id, data={"sub_device_limit_hard_mode": False, "sub_profile_title": "Бот"}))
        user = User(username="member", status=UserStatus.active, bot=bot)
        db.add(user)
        db.commit()

        settings = resolve_bot_settings(user)
        assert settings["sub_device_limit_hard_mode"] is True
        assert settings["sub_profile_title"] == "Бот"
