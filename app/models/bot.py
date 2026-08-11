from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.managed import ManagedStateResponse
from config import (
    BOT_URL,
    SUB_BS_LIMIT_ANNOUNCE_TEXT,
    SUB_CLIENT_NOTE,
    SUB_DEVICE_LIMIT_ANNOUNCE_TEXT,
    SUB_DEVICE_LIMIT_HARD_MODE,
    SUB_DEVICE_LIMIT_SERVER_TEXT,
    SUB_EXPIRED_ANNOUNCE_TEXT,
    SUB_EXPIRED_SERVER_TEXT,
    SUB_PROFILE_TITLE,
    SUB_PROFILE_URL,
    SUB_REVOKED_ANNOUNCE_TEXT,
    SUB_REVOKED_SERVER_TEXT,
    SUB_ROUTING_HAPP,
    SUB_ROUTING_V2RAYTUN,
    SUB_SUPPORT_URL,
    SUB_UNSUPPORTED_CLIENT_ANNOUNCE_TEXT,
    SUB_UNSUPPORTED_CLIENT_SERVER_TEXT,
    SUB_UPDATE_INTERVAL,
)


def _normalize_server_text(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


DEFAULT_BOT_SETTINGS: dict[str, Any] = {
    "sub_update_interval": str(SUB_UPDATE_INTERVAL),
    "sub_support_url": SUB_SUPPORT_URL,
    "sub_profile_title": SUB_PROFILE_TITLE,
    "sub_routing_happ": SUB_ROUTING_HAPP,
    "sub_routing_v2raytun": SUB_ROUTING_V2RAYTUN,
    "sub_client_note": SUB_CLIENT_NOTE,
    "sub_profile_url": SUB_PROFILE_URL,
    "sub_subscription_domain": "",
    "bot_url": BOT_URL,
    "web_url": "",
    "sub_revoked_announce_text": SUB_REVOKED_ANNOUNCE_TEXT,
    "sub_expired_announce_text": SUB_EXPIRED_ANNOUNCE_TEXT,
    "sub_device_limit_announce_text": SUB_DEVICE_LIMIT_ANNOUNCE_TEXT,
    "sub_device_limit_hard_mode": SUB_DEVICE_LIMIT_HARD_MODE,
    "sub_unsupported_client_announce_text": SUB_UNSUPPORTED_CLIENT_ANNOUNCE_TEXT,
    "sub_revoked_server_text": _normalize_server_text(SUB_REVOKED_SERVER_TEXT),
    "sub_expired_server_text": _normalize_server_text(SUB_EXPIRED_SERVER_TEXT),
    "sub_device_limit_server_text": _normalize_server_text(SUB_DEVICE_LIMIT_SERVER_TEXT),
    "sub_unsupported_client_server_text": _normalize_server_text(SUB_UNSUPPORTED_CLIENT_SERVER_TEXT),
    "bs_monthly_limit": 0,
    "bs_extra_reset_pool_on_prolong": False,
    "sub_bs_limit_server_text": [],
    "sub_bs_limit_announce_text": SUB_BS_LIMIT_ANNOUNCE_TEXT,
    "sub_v2ray_json_template": "",
    "sub_routing_json_default": "",
    "sub_routing_json_bs": "",
    "sub_custom_headers": "",
    "show_ads": True,
}


class BotBase(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    title: str | None = Field(None, max_length=128)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str):
        return value.strip().lstrip("@")


class BotCreate(BotBase):
    web_url: str | None = None


class BotUpdate(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    title: str | None = Field(None, max_length=128)
    web_url: str | None = None

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str):
        return value.strip().lstrip("@")


class BotResponse(BotBase):
    id: int
    source_bot_id: int | None = None
    admin_sync_enabled: bool
    managed: ManagedStateResponse | None = None
    model_config = ConfigDict(from_attributes=True)


class BotSettingsPayload(BaseModel):
    sub_update_interval: str = ""
    sub_support_url: str = ""
    sub_profile_title: str = ""
    sub_routing_happ: str = ""
    sub_routing_v2raytun: str = ""
    sub_client_note: str = ""
    sub_profile_url: str = ""
    sub_subscription_domain: str = ""
    bot_url: str = ""
    web_url: str = ""
    sub_revoked_announce_text: str = ""
    sub_expired_announce_text: str = ""
    sub_device_limit_announce_text: str = ""
    sub_device_limit_hard_mode: bool = False
    bs_monthly_limit: int = 0
    bs_extra_reset_pool_on_prolong: bool = False
    sub_unsupported_client_announce_text: str = ""
    sub_revoked_server_text: list[str] = []
    sub_expired_server_text: list[str] = []
    sub_device_limit_server_text: list[str] = []
    sub_unsupported_client_server_text: list[str] = []
    sub_bs_limit_server_text: list[str] = []
    sub_bs_limit_announce_text: str = ""
    sub_v2ray_json_template: str = ""
    sub_routing_json_default: str = ""
    sub_routing_json_bs: str = ""
    sub_custom_headers: str = ""
    show_ads: bool = True

    @field_validator(
        "sub_revoked_server_text",
        "sub_expired_server_text",
        "sub_device_limit_server_text",
        "sub_unsupported_client_server_text",
        "sub_bs_limit_server_text",
        mode="before",
    )
    @classmethod
    def validate_server_text(cls, value: Any):
        return _normalize_server_text(value)

    @field_validator("sub_subscription_domain", mode="before")
    @classmethod
    def validate_subscription_domain(cls, value: Any):
        from app.subscription.subscription_url import normalize_subscription_domain

        return normalize_subscription_domain(value)

    @field_validator(
        "sub_v2ray_json_template",
        "sub_routing_json_default",
        "sub_routing_json_bs",
        mode="before",
    )
    @classmethod
    def validate_json_field(cls, value: Any):
        from app.xray.bs_routing import parse_json_object

        # '' / None → допустимо (поле не задано); иначе обязан быть JSON-объект.
        parse_json_object(value)
        return value if value is not None else ""


class BotSettingsResponse(BotSettingsPayload):
    managed: ManagedStateResponse | None = None


class BotAdminSyncUpdate(BaseModel):
    enabled: bool


def apply_bot_settings_fallback(raw_settings: dict[str, Any] | None) -> dict[str, Any]:
    base = dict(DEFAULT_BOT_SETTINGS)
    text_fallback_keys = {
        "sub_client_note",
        "sub_revoked_announce_text",
        "sub_expired_announce_text",
        "sub_device_limit_announce_text",
        "sub_unsupported_client_announce_text",
        "sub_bs_limit_announce_text",
        "sub_subscription_domain",
    }
    server_text_fallback_keys = {
        "sub_revoked_server_text",
        "sub_expired_server_text",
        "sub_device_limit_server_text",
        "sub_unsupported_client_server_text",
        "sub_bs_limit_server_text",
    }
    if raw_settings:
        for key, value in raw_settings.items():
            if value is None:
                continue
            if key in text_fallback_keys and isinstance(value, str) and not value.strip():
                continue
            if key in server_text_fallback_keys and not _normalize_server_text(value):
                continue
            base[key] = value

    for key in (
        "sub_revoked_server_text",
        "sub_expired_server_text",
        "sub_device_limit_server_text",
        "sub_unsupported_client_server_text",
        "sub_bs_limit_server_text",
    ):
        base[key] = _normalize_server_text(base.get(key))

    base["sub_device_limit_hard_mode"] = bool(base.get("sub_device_limit_hard_mode"))
    base["bs_extra_reset_pool_on_prolong"] = bool(base.get("bs_extra_reset_pool_on_prolong", False))
    base["show_ads"] = bool(base.get("show_ads", True))

    return base
