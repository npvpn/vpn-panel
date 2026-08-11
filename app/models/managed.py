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
