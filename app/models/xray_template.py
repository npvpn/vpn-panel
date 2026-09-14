"""Pydantic-схемы API документов клиентского конфига и их версий (NPVPN-2024)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class XrayTemplateVersionMeta(BaseModel):
    version: int
    comment: str | None = None
    author_username: str = ""
    created_at: datetime | None = None
    size: int = 0


class XrayTemplateDocument(BaseModel):
    id: int
    slug: str
    title: str
    body: str = ""
    deletable: bool = False
    current: XrayTemplateVersionMeta | None = None


class XrayTemplateVersionBody(XrayTemplateVersionMeta):
    body: str = ""


class SaveTemplatePayload(BaseModel):
    body: str = ""
    comment: str | None = None


class CreateProfilePayload(BaseModel):
    slug: str
    title: str = ""


class CreatedProfile(BaseModel):
    id: int
    slug: str
    title: str
