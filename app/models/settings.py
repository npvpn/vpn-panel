from __future__ import annotations

import copy
import logging
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from config import SUB_ROUTING_HAPP, SUB_ROUTING_V2RAYTUN, SUBSCRIPTION_LEGACY_SECRET_KEYS

logger = logging.getLogger(__name__)

CLIENT_APPS_KEY = "client_apps"
PANEL_SETTINGS_KEY = "panel"

PANEL_SETTING_KEYS: tuple[str, ...] = (
    "sub_custom_headers",
    "bs_monthly_limit",
    "sub_routing_happ",
    "sub_routing_v2raytun",
    "sub_v2ray_json_template",
    "sub_routing_json_default",
    "sub_routing_json_bs",
    "subscription_legacy_secret_keys",
)

LEGACY_SECRET_KEYS_SETTING = "subscription_legacy_secret_keys"

DEFAULT_PANEL_SETTINGS: dict[str, Any] = {
    "sub_custom_headers": "",
    "bs_monthly_limit": 0,
    "sub_routing_happ": SUB_ROUTING_HAPP,
    "sub_routing_v2raytun": SUB_ROUTING_V2RAYTUN,
    "sub_v2ray_json_template": "",
    "sub_routing_json_default": "",
    "sub_routing_json_bs": "",
    "subscription_legacy_secret_keys": list(SUBSCRIPTION_LEGACY_SECRET_KEYS),
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

# Дефолты повторяют то, что до NPVPN-1657 было захардкожено в templates/sub/index.html.
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


class ClientAppsWithManagedResponse(ClientAppsPayload):
    managed: dict[str, Any] | None = None


def normalize_legacy_secret_keys(value: Any) -> list[str]:
    """Trim, drop empties, dedupe; accept list or comma-separated string."""
    if value is None:
        return []
    if isinstance(value, str):
        source: list[Any] = value.split(",")
    elif isinstance(value, (list, tuple)):
        source = list(value)
    else:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for item in source:
        key = str(item or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


class PanelSettingsPayload(BaseModel):
    sub_custom_headers: str = ""
    bs_monthly_limit: int = 0
    sub_routing_happ: str = ""
    sub_routing_v2raytun: str = ""
    sub_v2ray_json_template: str = ""
    sub_routing_json_default: str = ""
    sub_routing_json_bs: str = ""
    subscription_legacy_secret_keys: list[str] = Field(default_factory=list)

    @field_validator(
        "sub_v2ray_json_template",
        "sub_routing_json_default",
        "sub_routing_json_bs",
        mode="before",
    )
    @classmethod
    def validate_json_field(cls, value: Any):
        from app.xray.bs_routing import parse_json_object

        parse_json_object(value)
        return value if value is not None else ""

    @field_validator("subscription_legacy_secret_keys", mode="before")
    @classmethod
    def validate_legacy_secret_keys(cls, value: Any) -> list[str]:
        return normalize_legacy_secret_keys(value)


class PanelSettingsResponse(PanelSettingsPayload):
    """GET/PUT ответ: primary JWT только для чтения, в global_settings не пишется."""

    primary_jwt_secret: str = ""


def apply_panel_settings_fallback(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Настройки панели из БД, дополненные дефолтами. Битые поля не роняют чтение.

    `subscription_legacy_secret_keys`: ключа нет в JSON — env; ключ есть (в т.ч. []) — БД.
    """
    base = dict(DEFAULT_PANEL_SETTINGS)
    base[LEGACY_SECRET_KEYS_SETTING] = list(DEFAULT_PANEL_SETTINGS[LEGACY_SECRET_KEYS_SETTING])
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
            base[key] = normalize_legacy_secret_keys(raw[key])
            continue
        base[key] = raw[key]
    base["bs_monthly_limit"] = int(base.get("bs_monthly_limit") or 0)
    return base


def merge_client_apps_defaults(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Настройки из БД, дополненные дефолтами. Битые данные не роняют страницу подписки."""
    if not raw:
        return copy.deepcopy(DEFAULT_CLIENT_APPS)
    try:
        return ClientAppsPayload.model_validate(raw).model_dump()
    except ValidationError:
        logger.warning("Broken client_apps settings in DB, falling back to defaults", exc_info=True)
        return copy.deepcopy(DEFAULT_CLIENT_APPS)
