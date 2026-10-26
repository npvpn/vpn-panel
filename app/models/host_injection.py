"""Контракт композиции Xray-подписки; форма и JSON используют одну схему."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

import regex
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator, model_validator

MAX_ENDPOINTS = 512
SELECTION_SECONDS = 0.05


@lru_cache(maxsize=256)
def compile_selector(pattern: str):
    return regex.compile(pattern)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IdSelector(_Model):
    type: Literal["ids"]
    values: list[Annotated[StrictInt, Field(gt=0)]] = Field(min_length=1, max_length=256)

    @field_validator("values")
    @classmethod
    def unique_ids(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("Host IDs must be unique")
        return value


class RegexSelector(_Model):
    type: Literal["remarkRegex", "tagRegex"]
    pattern: str = Field(min_length=1, max_length=256)

    @field_validator("pattern")
    @classmethod
    def valid_regex(cls, value):
        try:
            compile_selector(value)
        except regex.error as exc:
            raise ValueError("Invalid host selector regex") from exc
        return value


class SameTagSelector(_Model):
    type: Literal["sameTagAsRecipient"]


class InjectionGroup(_Model):
    selector: Annotated[IdSelector | RegexSelector | SameTagSelector, Field(discriminator="type")]
    selectFrom: Literal["HIDDEN", "NOT_HIDDEN", "ALL"] = "HIDDEN"
    tagPrefix: str | None = Field(default=None, min_length=1, max_length=128)
    useHostRemarkAsTag: StrictBool = False
    useHostTagAsTag: StrictBool = False

    @model_validator(mode="after")
    def tagging_mode(self):
        if sum((self.tagPrefix is not None, self.useHostRemarkAsTag, self.useHostTagAsTag)) != 1:
            raise ValueError("Choose exactly one outbound tagging mode")
        if self.tagPrefix is not None and not self.tagPrefix.strip():
            raise ValueError("Tag prefix must not be blank")
        return self


class HostInjection(_Model):
    enabled: StrictBool = True
    injectHosts: list[InjectionGroup] = Field(default_factory=list, max_length=32)
    addVirtualHostAsOutbound: StrictBool = False

    @model_validator(mode="after")
    def meaningful_source(self):
        if self.enabled and not self.injectHosts and not self.addVirtualHostAsOutbound:
            raise ValueError("Select source hosts or enable the recipient's own connection")
        if not self.enabled and (self.injectHosts or self.addVirtualHostAsOutbound):
            raise ValueError("Disabled injection must not contain source settings")
        return self


class InjectionPreviewHost(_Model):
    id: Annotated[StrictInt, Field(gt=0)] | None = None
    inbound_tag: str = Field(default="", max_length=256)
    remark: str = Field(default="", max_length=512)
    group_tag: str = Field(default="", max_length=128)
    is_disabled: bool = False
    is_hidden: bool = False
    order: int = 0
    client_config_id: int | None = None
    # Keep invalid drafts intact so diagnostics can point to their exact field.
    host_injection: dict | None = None


class InjectionPreviewRequest(_Model):
    recipient: InjectionPreviewHost
    hosts: list[InjectionPreviewHost] = Field(default_factory=list, max_length=4096)
    excluded_host_ids: list[Annotated[StrictInt, Field(gt=0)]] = Field(default_factory=list, max_length=4096)
    template_body: str | None = Field(default=None, max_length=1_000_000)


class InjectionDiagnostic(_Model):
    code: str
    level: Literal["warning", "error"] = "warning"
    group: int | None = None
    host_id: int | None = None
    path: str = ""


class InjectionGroupPreview(_Model):
    group: int
    host_ids: list[int] = Field(default_factory=list)
    pattern: str = ""


class InjectionPreview(_Model):
    active: bool = False
    groups: list[InjectionGroupPreview] = Field(default_factory=list)
    issues: list[InjectionDiagnostic] = Field(default_factory=list)
