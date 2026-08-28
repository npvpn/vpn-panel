from __future__ import annotations

from functools import cache
from typing import Any

from app.db import GetDB, Session, crud
from app.db.models import JWT
from app.models.settings import (
    LEGACY_SECRET_KEYS_SETTING,
    PANEL_SETTINGS_KEY,
    PanelSettingsPayload,
    apply_panel_settings_fallback,
    normalize_legacy_secret_keys,
)

_SESSION_CACHE_KEY = "_panel_settings"


def get_panel_settings(db: Session) -> dict[str, Any]:
    """Текущие настройки панели, дополненные дефолтами. Кэш на сессию — один запрос на запрос."""
    cached = db.info.get(_SESSION_CACHE_KEY)
    if cached is not None:
        return cached
    settings = apply_panel_settings_fallback(crud.get_global_setting(db, PANEL_SETTINGS_KEY))
    db.info[_SESSION_CACHE_KEY] = settings
    return settings


def get_legacy_subscription_secret_keys(db: Session) -> list[str]:
    """Legacy-ключи проверки /sub/: из JSON настроек или env, если поля ещё нет."""
    return list(get_panel_settings(db).get(LEGACY_SECRET_KEYS_SETTING) or [])


@cache
def get_cached_legacy_subscription_secret_keys() -> tuple[str, ...]:
    """Process-wide кэш для горячего /sub/. Сбрасывается при save_panel_settings."""
    with GetDB() as db:
        return tuple(get_legacy_subscription_secret_keys(db))


def clear_legacy_subscription_secret_keys_cache() -> None:
    get_cached_legacy_subscription_secret_keys.cache_clear()


def get_primary_jwt_secret(db: Session) -> str:
    row = db.query(JWT).first()
    if row is None or not row.secret_key:
        return ""
    return str(row.secret_key)


def with_primary_jwt_secret(db: Session, settings: dict[str, Any]) -> dict[str, Any]:
    payload = dict(settings)
    payload["primary_jwt_secret"] = get_primary_jwt_secret(db)
    return payload


def save_panel_settings(db: Session, payload: PanelSettingsPayload) -> dict[str, Any]:
    """Сохранить настройки панели (payload уже провалидирован pydantic)."""
    data = payload.model_dump()
    if LEGACY_SECRET_KEYS_SETTING not in payload.model_fields_set:
        existing = crud.get_global_setting(db, PANEL_SETTINGS_KEY) or {}
        if LEGACY_SECRET_KEYS_SETTING in existing:
            data[LEGACY_SECRET_KEYS_SETTING] = normalize_legacy_secret_keys(existing[LEGACY_SECRET_KEYS_SETTING])
        else:
            data[LEGACY_SECRET_KEYS_SETTING] = list(apply_panel_settings_fallback(None)[LEGACY_SECRET_KEYS_SETTING])
    stored = crud.upsert_global_setting(db, PANEL_SETTINGS_KEY, data)
    settings = apply_panel_settings_fallback(stored)
    db.info[_SESSION_CACHE_KEY] = settings
    clear_legacy_subscription_secret_keys_cache()
    return settings


def get_bs_monthly_limit(db: Session | None) -> int:
    """Месячный БС-лимит в байтах. Без сессии — 0 (лимит не задан)."""
    if db is None:
        return 0
    return int(get_panel_settings(db).get("bs_monthly_limit") or 0)
