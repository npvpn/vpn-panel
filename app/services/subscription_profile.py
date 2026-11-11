from __future__ import annotations

from typing import Any

from app.db import Session, crud
from app.models.bot import SUBSCRIPTION_PROFILE_KEYS, SubscriptionProfilePayload, apply_bot_settings_fallback
from app.models.settings import SUBSCRIPTION_PROFILE_KEY


def get_subscription_profile(db: Session) -> dict[str, Any]:
    full = apply_bot_settings_fallback(crud.get_global_setting(db, SUBSCRIPTION_PROFILE_KEY))
    return {key: full[key] for key in SUBSCRIPTION_PROFILE_KEYS}


def save_subscription_profile(db: Session, payload: SubscriptionProfilePayload) -> dict[str, Any]:
    crud.upsert_global_setting(db, SUBSCRIPTION_PROFILE_KEY, payload.model_dump())
    return get_subscription_profile(db)
