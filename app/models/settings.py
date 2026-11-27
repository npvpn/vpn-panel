from __future__ import annotations

import copy
import logging
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from config import (
    SUB_BS_LIMIT_ANNOUNCE_TEXT,
    SUB_CLIENT_NOTE,
    SUB_DEVICE_LIMIT_ANNOUNCE_TEXT,
    SUB_DEVICE_LIMIT_SERVER_TEXT,
    SUB_EXPIRED_ANNOUNCE_TEXT,
    SUB_EXPIRED_SERVER_TEXT,
    SUB_REVOKED_ANNOUNCE_TEXT,
    SUB_REVOKED_SERVER_TEXT,
    SUB_ROUTING_HAPP,
    SUB_ROUTING_V2RAYTUN,
    SUB_TORRENT_BLOCK_ANNOUNCE_TEXT,
    SUB_TORRENT_BLOCK_SERVER_TEXT,
    SUB_UNSUPPORTED_CLIENT_ANNOUNCE_TEXT,
    SUB_UNSUPPORTED_CLIENT_SERVER_TEXT,
    SUB_UPDATE_INTERVAL,
    SUBSCRIPTION_LEGACY_SECRET_KEYS,
)

logger = logging.getLogger(__name__)

CLIENT_APPS_KEY = "client_apps"
PANEL_SETTINGS_KEY = "panel"

SUBSCRIPTION_MESSAGE_ANNOUNCE_KEYS: tuple[str, ...] = (
    "sub_client_note",
    "sub_revoked_announce_text",
    "sub_expired_announce_text",
    "sub_device_limit_announce_text",
    "sub_unsupported_client_announce_text",
    "sub_bs_limit_announce_text",
    "sub_torrent_block_announce_text",
)
SUBSCRIPTION_MESSAGE_SERVER_KEYS: tuple[str, ...] = (
    "sub_revoked_server_text",
    "sub_expired_server_text",
    "sub_device_limit_server_text",
    "sub_unsupported_client_server_text",
    "sub_bs_limit_server_text",
    "sub_torrent_block_server_text",
)
# Пустой список у этих заглушек — сохранённое «без текста», а не «вернуть заводское».
SERVER_TEXT_KEEP_EMPTY: frozenset[str] = frozenset({"sub_bs_limit_server_text", "sub_torrent_block_server_text"})
SUBSCRIPTION_MESSAGE_KEYS: tuple[str, ...] = (
    *SUBSCRIPTION_MESSAGE_ANNOUNCE_KEYS,
    *SUBSCRIPTION_MESSAGE_SERVER_KEYS,
)

PANEL_SETTING_KEYS: tuple[str, ...] = (
    "sub_custom_headers",
    "bs_monthly_limit",
    "sub_routing_happ",
    "sub_routing_v2raytun",
    "subscription_legacy_secret_keys",
    "sub_device_limit_hard_mode",
    "sub_update_interval",
    *SUBSCRIPTION_MESSAGE_KEYS,
)

LEGACY_SECRET_KEYS_SETTING = "subscription_legacy_secret_keys"


def normalize_server_text(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.replace("\n", ",").split(",") if item.strip()]
    return []


DEFAULT_PANEL_SETTINGS: dict[str, Any] = {
    "sub_custom_headers": "",
    "bs_monthly_limit": 0,
    "sub_routing_happ": SUB_ROUTING_HAPP,
    "sub_routing_v2raytun": SUB_ROUTING_V2RAYTUN,
    "subscription_legacy_secret_keys": list(SUBSCRIPTION_LEGACY_SECRET_KEYS),
    "sub_client_note": SUB_CLIENT_NOTE,
    "sub_revoked_announce_text": SUB_REVOKED_ANNOUNCE_TEXT,
    "sub_expired_announce_text": SUB_EXPIRED_ANNOUNCE_TEXT,
    "sub_device_limit_announce_text": SUB_DEVICE_LIMIT_ANNOUNCE_TEXT,
    "sub_unsupported_client_announce_text": SUB_UNSUPPORTED_CLIENT_ANNOUNCE_TEXT,
    "sub_bs_limit_announce_text": SUB_BS_LIMIT_ANNOUNCE_TEXT,
    "sub_torrent_block_announce_text": SUB_TORRENT_BLOCK_ANNOUNCE_TEXT,
    "sub_revoked_server_text": normalize_server_text(SUB_REVOKED_SERVER_TEXT),
    "sub_expired_server_text": normalize_server_text(SUB_EXPIRED_SERVER_TEXT),
    "sub_device_limit_server_text": normalize_server_text(SUB_DEVICE_LIMIT_SERVER_TEXT),
    "sub_unsupported_client_server_text": normalize_server_text(SUB_UNSUPPORTED_CLIENT_SERVER_TEXT),
    "sub_bs_limit_server_text": [],
    "sub_torrent_block_server_text": normalize_server_text(SUB_TORRENT_BLOCK_SERVER_TEXT),
    "sub_device_limit_hard_mode": False,
    "sub_update_interval": str(SUB_UPDATE_INTERVAL),
}

PLATFORMS: tuple[str, ...] = ("ios", "macos", "android", "androidtv", "windows", "linux")

LINK_KEYS: tuple[str, ...] = (
    "ios_ru",
    "ios_global",
    "macos_ru",
    "macos_global",
    "android",
    "androidtv",
    "windows",
    "linux",
)

MAX_LINK_LENGTH = 512

_HAPP_APPSTORE_GLOBAL = "https://apps.apple.com/us/app/happ-proxy-utility/id6504287215"
_INCY_APPSTORE_RU = "https://apps.apple.com/ru/app/incy/id6756943388"
_INCY_APPSTORE_GLOBAL = "https://apps.apple.com/us/app/incy/id6756943388"

# У Happ пустая ru-ссылка: приложения в российском App Store нет.
DEFAULT_CLIENT_APPS: dict[str, Any] = {
    "apps": [
        {
            "id": "happ",
            "name": "Happ Proxy",
            "scheme": "happ",
            "enabled": True,
            "links": {
                "ios_ru": "",
                "ios_global": _HAPP_APPSTORE_GLOBAL,
                "macos_ru": "",
                "macos_global": _HAPP_APPSTORE_GLOBAL,
                "android": "https://play.google.com/store/apps/details?id=com.happproxy&hl=ru",
                "androidtv": "https://play.google.com/store/apps/details?id=com.happproxy",
                "windows": "https://github.com/Happ-proxy/happ-desktop/releases/latest/download/setup-Happ.x64.exe",
                "linux": "https://github.com/Happ-proxy/happ-desktop/releases/latest/download/Happ.linux.x64.deb",
            },
        },
        {
            "id": "incy",
            "name": "Incy",
            "scheme": "incy",
            "enabled": True,
            "links": {
                "ios_ru": _INCY_APPSTORE_RU,
                "ios_global": _INCY_APPSTORE_GLOBAL,
                "macos_ru": _INCY_APPSTORE_RU,
                "macos_global": _INCY_APPSTORE_GLOBAL,
                "android": "https://play.google.com/store/apps/details?id=llc.itdev.incy",
                "androidtv": "",
                "windows": "https://incy.cc/",
                "linux": "",
            },
        },
        {
            "id": "v2raytun",
            "name": "v2RayTun",
            "scheme": "v2raytun",
            "enabled": True,
            "links": {
                "ios_ru": "",
                "ios_global": "",
                "macos_ru": "",
                "macos_global": "",
                "android": "https://play.google.com/store/apps/details?id=com.v2raytun.android&hl=ru",
                "androidtv": "",
                "windows": "https://v2raytun.com/",
                "linux": "",
            },
        },
    ],
    "primary_by_platform": {
        "ios": "incy",
        "macos": "incy",
        "android": "happ",
        "windows": "happ",
        "linux": "happ",
        "androidtv": "happ",
    },
}


class ClientApp(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_-]{1,32}$")
    name: str = Field(min_length=1, max_length=64)
    # Схема deeplink без "://": ссылка строится как {scheme}://add/{subscription_url}.
    scheme: str = Field(pattern=r"^[a-z][a-z0-9+.-]{0,31}$")
    enabled: bool = True
    links: dict[str, str] = Field(default_factory=dict)

    @field_validator("scheme")
    @classmethod
    def validate_scheme(cls, value: str) -> str:
        if value in {"javascript", "data", "vbscript", "file"}:
            raise ValueError(f"scheme {value!r} is not allowed")
        return value

    @field_validator("links")
    @classmethod
    def validate_links(cls, value: dict[str, str]) -> dict[str, str]:
        cleaned: dict[str, str] = {}
        for key in LINK_KEYS:
            raw = str(value.get(key) or "").strip()
            if not raw:
                cleaned[key] = ""
                continue
            if not raw.startswith(("http://", "https://")):
                raise ValueError(f"link {key!r} must be an http(s) URL")
            if len(raw) > MAX_LINK_LENGTH:
                raise ValueError(f"link {key!r} is longer than {MAX_LINK_LENGTH} characters")
            cleaned[key] = raw
        return cleaned


class ClientAppsPayload(BaseModel):
    apps: list[ClientApp] = Field(default_factory=list)
    primary_by_platform: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_consistency(self) -> ClientAppsPayload:
        ids = [app.id for app in self.apps]
        if len(ids) != len(set(ids)):
            raise ValueError("app ids must be unique")

        enabled_ids = {app.id for app in self.apps if app.enabled}
        for platform, app_id in self.primary_by_platform.items():
            if platform not in PLATFORMS:
                raise ValueError(f"unknown platform {platform!r}")
            if app_id and app_id not in enabled_ids:
                raise ValueError(f"primary app {app_id!r} for {platform!r} is unknown or disabled")
        return self


def _legacy_secret_record(item: Any) -> dict[str, str] | None:
    if isinstance(item, dict):
        secret = str(item.get("secret_key") or "").strip()
        username = str(item.get("bot_username") or "").strip().lstrip("@")[:64]
    else:
        secret = str(item or "").strip()
        username = ""
    if not secret:
        return None
    return {"secret_key": secret, "bot_username": username}


def normalize_legacy_secret_key_records(value: Any) -> list[dict[str, str]]:
    """Trim, drop empties, dedupe by secret. The first record wins, including an empty username."""
    if value is None:
        return []
    if isinstance(value, str):
        source: list[Any] = value.split(",")
    elif isinstance(value, (list, tuple)):
        source = list(value)
    else:
        return []
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for item in source:
        record = _legacy_secret_record(item)
        if record is None or record["secret_key"] in seen:
            continue
        seen.add(record["secret_key"])
        out.append(record)
    return out


def normalize_legacy_secret_keys(value: Any) -> list[str]:
    """Секреты без username: проверка /sub/ и старые строковые значения."""
    return [record["secret_key"] for record in normalize_legacy_secret_key_records(value)]


def merge_legacy_secret_keys_since_load(baseline: Any, edited: Any, current: Any) -> list[dict[str, str]]:
    """Список формы плюс ключи, которых не было в снимке на момент её загрузки.

    Удаление и правка username относятся к ключам, которые форма уже видела.
    Ключ, добавленный другой сессией после загрузки, в снимке отсутствует и остаётся.
    """
    known = {record["secret_key"] for record in normalize_legacy_secret_key_records(baseline)}
    merged = normalize_legacy_secret_key_records(edited)
    seen = {record["secret_key"] for record in merged}
    for record in normalize_legacy_secret_key_records(current):
        secret = record["secret_key"]
        if secret in known or secret in seen:
            continue
        merged.append(record)
        seen.add(secret)
    return merged


DEFAULT_PANEL_SETTINGS[LEGACY_SECRET_KEYS_SETTING] = normalize_legacy_secret_key_records(
    DEFAULT_PANEL_SETTINGS[LEGACY_SECRET_KEYS_SETTING]
)


class LegacySubscriptionSecretKeyPayload(BaseModel):
    """Один ключ старой внешней панели для проверки её выданных ссылок."""

    secret_key: str = Field(min_length=1, max_length=64)
    bot_username: str = ""

    @field_validator("secret_key")
    @classmethod
    def validate_secret_key(cls, value: str) -> str:
        key = value.strip()
        if not key:
            raise ValueError("secret_key must not be empty")
        return key

    @field_validator("bot_username", mode="before")
    @classmethod
    def validate_bot_username(cls, value: Any) -> str:
        return str(value or "").strip().lstrip("@")[:64]


class PanelSettingsPayload(BaseModel):
    sub_custom_headers: str = ""
    bs_monthly_limit: int = 0
    sub_routing_happ: str = ""
    sub_routing_v2raytun: str = ""
    subscription_legacy_secret_keys: list[dict[str, str]] = Field(default_factory=list)
    # Снимок списка на момент загрузки формы. В настройки не пишется: по нему
    # сохранение отличает правку ключей от списка, устаревшего из-за импорта.
    subscription_legacy_secret_keys_baseline: list[dict[str, str]] | None = Field(default=None, exclude=True)
    sub_client_note: str = ""
    sub_revoked_announce_text: str = ""
    sub_expired_announce_text: str = ""
    sub_device_limit_announce_text: str = ""
    sub_unsupported_client_announce_text: str = ""
    sub_bs_limit_announce_text: str = ""
    sub_torrent_block_announce_text: str = ""
    sub_revoked_server_text: list[str] = Field(default_factory=list)
    sub_expired_server_text: list[str] = Field(default_factory=list)
    sub_device_limit_server_text: list[str] = Field(default_factory=list)
    sub_unsupported_client_server_text: list[str] = Field(default_factory=list)
    sub_bs_limit_server_text: list[str] = Field(default_factory=list)
    sub_torrent_block_server_text: list[str] = Field(default_factory=list)
    sub_device_limit_hard_mode: bool = False
    sub_update_interval: str = ""

    @field_validator("subscription_legacy_secret_keys", mode="before")
    @classmethod
    def validate_legacy_secret_keys(cls, value: Any) -> list[dict[str, str]]:
        return normalize_legacy_secret_key_records(value)

    @field_validator("subscription_legacy_secret_keys_baseline", mode="before")
    @classmethod
    def validate_legacy_secret_keys_baseline(cls, value: Any) -> list[dict[str, str]] | None:
        if value is None:
            return None
        return normalize_legacy_secret_key_records(value)

    @field_validator(
        "sub_revoked_server_text",
        "sub_expired_server_text",
        "sub_device_limit_server_text",
        "sub_unsupported_client_server_text",
        "sub_bs_limit_server_text",
        "sub_torrent_block_server_text",
        mode="before",
    )
    @classmethod
    def validate_server_text(cls, value: Any) -> list[str]:
        return normalize_server_text(value)


class PanelSettingsResponse(PanelSettingsPayload):
    """GET/PUT ответ: primary JWT только для чтения, в global_settings не пишется."""

    primary_jwt_secret: str = ""


def apply_panel_settings_fallback(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Настройки панели из БД, дополненные дефолтами. Битые поля не роняют чтение.

    `subscription_legacy_secret_keys`: ключа нет в JSON — env; ключ есть (в т.ч. []) — БД.
    """
    base = dict(DEFAULT_PANEL_SETTINGS)
    base[LEGACY_SECRET_KEYS_SETTING] = normalize_legacy_secret_key_records(
        DEFAULT_PANEL_SETTINGS[LEGACY_SECRET_KEYS_SETTING]
    )
    if not raw:
        return base
    for key in PANEL_SETTING_KEYS:
        if key not in raw or raw[key] is None:
            continue
        if key == "bs_monthly_limit":
            try:
                base[key] = int(raw[key] or 0)
            except (TypeError, ValueError):
                continue
            continue
        if key == LEGACY_SECRET_KEYS_SETTING:
            base[key] = normalize_legacy_secret_key_records(raw[key])
            continue
        if key == "sub_update_interval":
            value = str(raw[key] or "").strip()
            if value:
                base[key] = value
            continue
        if key in SUBSCRIPTION_MESSAGE_ANNOUNCE_KEYS:
            text = str(raw[key] or "")
            if text.strip():
                base[key] = text
            continue
        if key in SUBSCRIPTION_MESSAGE_SERVER_KEYS:
            lines = normalize_server_text(raw[key])
            # Пустой список у БС-заглушки — валидное сохранённое значение.
            # Для остальных server-text пустое значит «взять заводское».
            if lines or key in SERVER_TEXT_KEEP_EMPTY:
                base[key] = lines
            continue
        base[key] = raw[key]
    base["bs_monthly_limit"] = int(base.get("bs_monthly_limit") or 0)
    base["sub_device_limit_hard_mode"] = bool(base.get("sub_device_limit_hard_mode"))
    for key in SUBSCRIPTION_MESSAGE_SERVER_KEYS:
        base[key] = normalize_server_text(base.get(key))
    return base


def overlay_subscription_messages(
    bot_settings: dict[str, Any], panel_settings: dict[str, Any] | None
) -> dict[str, Any]:
    """Тексты объявлений/серверов — из панели; остальные ключи bot_settings без изменений."""
    merged = dict(bot_settings)
    source = panel_settings if isinstance(panel_settings, dict) else {}
    for key in SUBSCRIPTION_MESSAGE_ANNOUNCE_KEYS:
        raw = source[key] if key in source else merged.get(key, DEFAULT_PANEL_SETTINGS[key])
        text = str(raw or "")
        merged[key] = text if text.strip() else DEFAULT_PANEL_SETTINGS[key]
    for key in SUBSCRIPTION_MESSAGE_SERVER_KEYS:
        raw = source[key] if key in source else merged.get(key, DEFAULT_PANEL_SETTINGS[key])
        lines = normalize_server_text(raw)
        if lines or (key in SERVER_TEXT_KEEP_EMPTY and key in source):
            merged[key] = lines
        else:
            merged[key] = list(DEFAULT_PANEL_SETTINGS[key])
    return merged


def merge_client_apps_defaults(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Настройки из БД, дополненные дефолтами. Битые данные не роняют страницу подписки."""
    if not raw:
        return copy.deepcopy(DEFAULT_CLIENT_APPS)
    try:
        return ClientAppsPayload.model_validate(raw).model_dump()
    except ValidationError:
        logger.warning("Broken client_apps settings in DB, falling back to defaults", exc_info=True)
        return copy.deepcopy(DEFAULT_CLIENT_APPS)
