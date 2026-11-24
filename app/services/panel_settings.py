from __future__ import annotations

from functools import cache
from typing import Any, cast

from app.db import GetDB, Session, crud
from app.db.models import JWT, GlobalSetting
from app.models.settings import (
    LEGACY_SECRET_KEYS_SETTING,
    PANEL_SETTINGS_KEY,
    PanelSettingsPayload,
    apply_panel_settings_fallback,
    merge_legacy_secret_keys_since_load,
    normalize_legacy_secret_key_records,
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
    """Секреты legacy-ключей для проверки /sub/. Username в подпись не входит."""
    return normalize_legacy_secret_keys(get_panel_settings(db).get(LEGACY_SECRET_KEYS_SETTING))


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


def add_legacy_subscription_secret_key(db: Session, secret_key: str, bot_username: str = "") -> None:
    """Добавить ключ, не перезаписывая настройки панели и username уже лежащего секрета."""
    row = _panel_settings_row_for_update(db)
    data = dict(row.data) if row is not None and row.data else {}
    if LEGACY_SECRET_KEYS_SETTING in data:
        records = normalize_legacy_secret_key_records(data.get(LEGACY_SECRET_KEYS_SETTING))
    else:
        records = normalize_legacy_secret_key_records(apply_panel_settings_fallback(None)[LEGACY_SECRET_KEYS_SETTING])
    key = secret_key.strip()
    if key and not any(record["secret_key"] == key for record in records):
        records.append(
            {
                "secret_key": key,
                "bot_username": str(bot_username or "").strip().lstrip("@")[:64],
            }
        )
    data[LEGACY_SECRET_KEYS_SETTING] = records
    if row is None:
        db.add(GlobalSetting(key=PANEL_SETTINGS_KEY, data=data))
    else:
        cast(Any, row).data = data
    db.commit()
    db.info.pop(_SESSION_CACHE_KEY, None)
    clear_legacy_subscription_secret_keys_cache()


def _panel_settings_row_for_update(db: Session) -> GlobalSetting | None:
    """Единая точка сериализации всех записей JSON-настроек панели."""
    return db.query(GlobalSetting).filter(GlobalSetting.key == PANEL_SETTINGS_KEY).with_for_update().first()


def _stored_legacy_secret_key_records(existing: dict[str, Any]) -> list[dict[str, str]]:
    """Ключи, которые сейчас действуют: записанный список либо env, если поля в JSON нет."""
    if LEGACY_SECRET_KEYS_SETTING in existing:
        return normalize_legacy_secret_key_records(existing[LEGACY_SECRET_KEYS_SETTING])
    return normalize_legacy_secret_key_records(apply_panel_settings_fallback(None)[LEGACY_SECRET_KEYS_SETTING])


def save_panel_settings(db: Session, payload: PanelSettingsPayload) -> dict[str, Any]:
    """Сохранить настройки панели (payload уже провалидирован pydantic)."""
    row = _panel_settings_row_for_update(db)
    existing = dict(row.data) if row is not None and row.data else {}
    data = payload.model_dump()
    if LEGACY_SECRET_KEYS_SETTING not in payload.model_fields_set:
        data[LEGACY_SECRET_KEYS_SETTING] = _stored_legacy_secret_key_records(existing)
    elif payload.subscription_legacy_secret_keys_baseline is not None:
        # Форма прислала список, который видела при загрузке. Ключи, добавленные
        # после этого, не входят в её снимок и не должны затираться сохранением.
        data[LEGACY_SECRET_KEYS_SETTING] = merge_legacy_secret_keys_since_load(
            payload.subscription_legacy_secret_keys_baseline,
            data[LEGACY_SECRET_KEYS_SETTING],
            _stored_legacy_secret_key_records(existing),
        )
    if "sub_device_limit_hard_mode" not in payload.model_fields_set:
        if "sub_device_limit_hard_mode" in existing:
            data["sub_device_limit_hard_mode"] = bool(existing["sub_device_limit_hard_mode"])
    if row is None:
        row = GlobalSetting(key=PANEL_SETTINGS_KEY, data=data)
        db.add(row)
    else:
        cast(Any, row).data = data
    db.commit()
    settings = apply_panel_settings_fallback(dict(row.data))
    db.info[_SESSION_CACHE_KEY] = settings
    clear_legacy_subscription_secret_keys_cache()
    return settings


def get_bs_monthly_limit(db: Session | None) -> int:
    """Месячный БС-лимит в байтах. Без сессии — 0 (лимит не задан)."""
    if db is None:
        return 0
    return int(get_panel_settings(db).get("bs_monthly_limit") or 0)
