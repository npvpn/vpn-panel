from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ManagedPushRequest(BaseModel):
    data: dict[str, Any] = Field(default_factory=dict)
    version: str = ""
    source: str = ""


class ManagedBotSettingsPayload(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    title: str | None = Field(None, max_length=128)
    bot_url: str
    web_url: str
    sub_support_url: str
    sub_subscription_domain: str
    sub_pay_url: str | None = None
    show_ads: bool | None = None
    sub_profile_url: str | None = None
    sub_profile_title: str | None = None
    sub_update_interval: str | None = None
    bs_extra_reset_pool_on_prolong: bool | None = None
    sub_device_limit_hard_mode: bool | None = None
    model_config = ConfigDict(extra="forbid")

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        normalized = value.strip().lstrip("@")
        if not normalized:
            raise ValueError("Bot username is required")
        return normalized

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        return value.strip() if value and value.strip() else None

    @field_validator("sub_subscription_domain", mode="before")
    @classmethod
    def normalize_subscription_domain(cls, value: Any) -> str:
        from app.subscription.subscription_url import normalize_subscription_domain

        return normalize_subscription_domain(value)


class ManagedStateResponse(BaseModel):
    key: str
    version: str
    source: str
    applied_at: Any = None
