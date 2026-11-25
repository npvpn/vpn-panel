"""Pydantic-схемы API документов клиентского конфига и их версий (NPVPN-2024)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.models.host_injection import HostInjection


class XrayTemplateVersionMeta(BaseModel):
    version: int
    comment: str | None = None
    author_username: str = ""
    created_at: datetime | None = None
    size: int = 0


class XrayTemplateHost(BaseModel):
    remark: str
    inbound_tag: str


class XrayTemplateDocument(BaseModel):
    id: int
    slug: str
    title: str
    body: str = ""
    deletable: bool = False
    # Можно ли архивировать. Совпадает с deletable: default архивировать нельзя.
    archivable: bool = False
    archived_at: datetime | None = None
    archived_by: str | None = None
    hosts: list[XrayTemplateHost] = []
    current: XrayTemplateVersionMeta | None = None
    effective_injection: HostInjection | None = None
    effective_injection_error: bool = False


class XrayTemplateVersionBody(XrayTemplateVersionMeta):
    body: str = ""


class SaveTemplatePayload(BaseModel):
    body: str = ""
    comment: str | None = None


class CreateConfigPayload(BaseModel):
    slug: str
    title: str = ""


class CreatedConfig(BaseModel):
    id: int
    slug: str
    title: str
