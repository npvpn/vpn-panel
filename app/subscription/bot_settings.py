from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import object_session

from app.models.bot import apply_bot_settings_fallback

if TYPE_CHECKING:
    from app.db.models import User


def resolve_bot_settings(user: User) -> dict[str, Any]:
    raw = None
    session = object_session(user) if user is not None else None
    if user is not None and user.bot is not None:
        raw = user.bot.settings.data if user.bot.settings is not None else None
    elif session is not None:
        from app.services.subscription_profile import get_raw_subscription_profile, is_solo_panel

        if is_solo_panel(session):
            raw = get_raw_subscription_profile(session)

    settings = apply_bot_settings_fallback(raw)
    if session is not None:
        from app.services.panel_settings import get_panel_settings

        settings["sub_device_limit_hard_mode"] = bool(
            get_panel_settings(session).get("sub_device_limit_hard_mode")
        )
    return settings
