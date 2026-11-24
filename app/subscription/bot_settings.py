from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import object_session

from app.models.bot import apply_bot_settings_fallback
from app.models.settings import DEFAULT_PANEL_SETTINGS

if TYPE_CHECKING:
    from app.db.models import User


def resolve_bot_settings(user: User) -> dict[str, Any]:
    raw = None
    session = object_session(user) if user is not None else None
    if user is not None and user.bot is not None:
        raw = user.bot.settings.data if user.bot.settings is not None else None

    settings = apply_bot_settings_fallback(raw)
    settings["sub_update_interval"] = str(DEFAULT_PANEL_SETTINGS["sub_update_interval"])
    if session is not None:
        from app.services.panel_settings import get_panel_settings

        panel_settings = get_panel_settings(session)
        settings["sub_device_limit_hard_mode"] = bool(panel_settings.get("sub_device_limit_hard_mode"))
        settings["sub_update_interval"] = str(
            panel_settings.get("sub_update_interval") or DEFAULT_PANEL_SETTINGS["sub_update_interval"]
        )
    return settings
