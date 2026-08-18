from __future__ import annotations

from typing import Any

from app.db import Session, crud
from app.models.settings import (
    PANEL_SETTINGS_KEY,
    PanelSettingsPayload,
    apply_panel_settings_fallback,
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


def save_panel_settings(db: Session, payload: PanelSettingsPayload) -> dict[str, Any]:
    """Сохранить настройки панели (payload уже провалидирован pydantic)."""
    stored = crud.upsert_global_setting(db, PANEL_SETTINGS_KEY, payload.model_dump())
    settings = apply_panel_settings_fallback(stored)
    db.info[_SESSION_CACHE_KEY] = settings
    return settings


def get_bs_monthly_limit(db: Session | None) -> int:
    """Месячный БС-лимит в байтах. Без сессии — 0 (лимит не задан)."""
    if db is None:
        return 0
    return int(get_panel_settings(db).get("bs_monthly_limit") or 0)
