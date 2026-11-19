from __future__ import annotations

from typing import Any

from app.db import Session, crud
from app.models.bot import SUBSCRIPTION_PROFILE_KEYS, SubscriptionProfilePayload, apply_bot_settings_fallback
from app.models.settings import SUBSCRIPTION_PROFILE_KEY

_SESSION_CACHE_KEY = "_subscription_profile"
_SOLO_PANEL_CACHE_KEY = "_is_solo_panel"


def is_solo_panel(db: Session) -> bool:
    """Whether the subscription is served by the panel, not a bot."""
    if _SOLO_PANEL_CACHE_KEY not in db.info:
        db.info[_SOLO_PANEL_CACHE_KEY] = crud.count_bots(db) == 0
    return db.info[_SOLO_PANEL_CACHE_KEY]


def get_raw_subscription_profile(db: Session) -> dict[str, Any] | None:
    if _SESSION_CACHE_KEY not in db.info:
        db.info[_SESSION_CACHE_KEY] = crud.get_global_setting(db, SUBSCRIPTION_PROFILE_KEY)
    return db.info[_SESSION_CACHE_KEY]


def get_subscription_profile(db: Session) -> dict[str, Any]:
    full = apply_bot_settings_fallback(get_raw_subscription_profile(db))
    return {key: full[key] for key in SUBSCRIPTION_PROFILE_KEYS}


def save_subscription_profile(db: Session, payload: SubscriptionProfilePayload) -> dict[str, Any]:
    db.info[_SESSION_CACHE_KEY] = crud.upsert_global_setting(db, SUBSCRIPTION_PROFILE_KEY, payload.model_dump())
    return get_subscription_profile(db)
