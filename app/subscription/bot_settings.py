from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.models.bot import apply_bot_settings_fallback

if TYPE_CHECKING:
    from app.db.models import User


def resolve_bot_settings(user: User) -> dict[str, Any]:
    if user and user.bot and user.bot.settings:
        return apply_bot_settings_fallback(user.bot.settings.data)
    return apply_bot_settings_fallback(None)
