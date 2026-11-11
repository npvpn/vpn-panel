from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import object_session

from app.models.bot import apply_bot_settings_fallback

if TYPE_CHECKING:
    from app.db.models import User


def resolve_bot_settings(user: User) -> dict[str, Any]:
    if user is not None and user.bot is not None:
        data = user.bot.settings.data if user.bot.settings is not None else None
        return apply_bot_settings_fallback(data)
    raw = None
    session = object_session(user) if user is not None else None
    if session is not None:
        from app.db.crud import get_global_setting
        from app.models.settings import SUBSCRIPTION_PROFILE_KEY

        raw = get_global_setting(session, SUBSCRIPTION_PROFILE_KEY)
    return apply_bot_settings_fallback(raw)
