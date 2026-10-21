from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.managed import ManagedStateResponse
from app.models.settings import PANEL_SETTING_KEYS
from config import (
    BOT_URL,
    SUB_DEVICE_LIMIT_HARD_MODE,
    SUB_PROFILE_TITLE,
    SUB_PROFILE_URL,
    SUB_SUPPORT_URL,
    SUB_UPDATE_INTERVAL,
)

DEFAULT_BOT_SETTINGS: dict[str, Any] = {
    "sub_update_interval": str(SUB_UPDATE_INTERVAL),
    "sub_support_url": SUB_SUPPORT_URL,
    "sub_profile_title": SUB_PROFILE_TITLE,
    "sub_profile_url": SUB_PROFILE_URL,
    "sub_subscription_domain": "",
    "bot_url": BOT_URL,
    "web_url": "",
    "sub_pay_url": "",
    "chat_base_url": "",
    "chat_website_token": "",
    "chat_identity_url": "",
    "sub_device_limit_hard_mode": SUB_DEVICE_LIMIT_HARD_MODE,
    "bs_extra_reset_pool_on_prolong": False,
    "show_ads": True,
    # NPVPN-2072. Источник истины — админка бота; здесь дефолт на случай, когда синк
    # ещё не доехал. Выключено по умолчанию: включение меняет выдачу адресов всем сразу.
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
    sub_profile_url: str = ""
    sub_subscription_domain: str = ""
    bot_url: str = ""
    web_url: str = ""
    sub_pay_url: str = ""
    chat_base_url: str = ""
    chat_website_token: str = ""
    chat_identity_url: str = ""
    sub_device_limit_hard_mode: bool = False
    bs_extra_reset_pool_on_prolong: bool = False
    show_ads: bool = True

    @field_validator("sub_subscription_domain", mode="before")
    @classmethod
    def validate_subscription_domain(cls, value: Any):
        from app.subscription.subscription_url import normalize_subscription_domain

        return normalize_subscription_domain(value)


class BotSettingsResponse(BotSettingsPayload):
    managed: ManagedStateResponse | None = None


class BotAdminSyncUpdate(BaseModel):
    enabled: bool


def apply_bot_settings_fallback(raw_settings: dict[str, Any] | None) -> dict[str, Any]:
    base = dict(DEFAULT_BOT_SETTINGS)
    text_fallback_keys = {
        "sub_subscription_domain",
    }
    if raw_settings:
        for key, value in raw_settings.items():
            if key in PANEL_SETTING_KEYS:
                continue
            if value is None:
                continue
            if key in text_fallback_keys and isinstance(value, str) and not value.strip():
                continue
            base[key] = value

    base["sub_device_limit_hard_mode"] = bool(base.get("sub_device_limit_hard_mode"))
    base["bs_extra_reset_pool_on_prolong"] = bool(base.get("bs_extra_reset_pool_on_prolong", False))
    base["show_ads"] = bool(base.get("show_ads", True))

    return base
