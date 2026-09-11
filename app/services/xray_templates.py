"""Документы клиентского конфига и их версии (NPVPN-2024).

Append-only: активная редакция — версия с максимальным номером.
"""

from __future__ import annotations

from functools import cache
from typing import Any

from sqlalchemy import func

from app.db import GetDB, Session
from app.db.models import TEMPLATE_KIND, XrayTemplate, XrayTemplateVersion

_SESSION_CACHE_KEY = "_xray_templates"


def get_active_bodies(db: Session) -> dict[str, Any]:
    """{"template": str, "profiles": {template_id: body}} — только непустые тела профилей.

    Кэш на сессию БД: /sub/ — горячий путь, лишних запросов на подписку быть не должно.
    """
    cached = db.info.get(_SESSION_CACHE_KEY)
    if cached is not None:
        return cached
    latest = (
        db.query(
            XrayTemplateVersion.template_id.label("template_id"),
            func.max(XrayTemplateVersion.version).label("max_version"),
        )
        .group_by(XrayTemplateVersion.template_id)
        .subquery()
    )
    rows = (
        db.query(XrayTemplate.id, XrayTemplate.kind, XrayTemplateVersion.body)
        .join(XrayTemplateVersion, XrayTemplateVersion.template_id == XrayTemplate.id)
        .join(
            latest,
            (latest.c.template_id == XrayTemplateVersion.template_id)
            & (latest.c.max_version == XrayTemplateVersion.version),
        )
        .all()
    )
    bodies: dict[str, Any] = {"template": "", "profiles": {}}
    for template_id, kind, body in rows:
        if kind == TEMPLATE_KIND:
            bodies["template"] = body or ""
        elif (body or "").strip():
            bodies["profiles"][template_id] = body
    db.info[_SESSION_CACHE_KEY] = bodies
    return bodies


@cache
def get_cached_active_bodies() -> dict[str, Any]:
    """Процессный кэш для горячего /sub/. Сбрасывается при любой записи версии (Task 3)."""
    with GetDB() as db:
        return get_active_bodies(db)


def invalidate(db: Session) -> None:
    db.info.pop(_SESSION_CACHE_KEY, None)
    get_cached_active_bodies.cache_clear()
