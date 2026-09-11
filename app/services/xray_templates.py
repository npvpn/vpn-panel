"""Документы клиентского конфига и их версии (NPVPN-2024).

Append-only: активная редакция — версия с максимальным номером.
"""

from __future__ import annotations

from functools import cache
from typing import Any

from sqlalchemy import func

from app.db import GetDB, Session
from app.db.models import DEFAULT_PROFILE_SLUG, PROFILE_KIND, TEMPLATE_KIND, Node, XrayTemplate, XrayTemplateVersion
from app.xray.routing_profiles import parse_json_object

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


class XrayTemplateError(Exception):
    """Нарушение правил документов: дубль slug, удаление неудаляемого. → 409."""


class InvalidTemplateBody(Exception):
    """Тело не является JSON-объектом. → 422."""


def _validate(body: str | None) -> str:
    try:
        parse_json_object(body)
    except ValueError as exc:
        raise InvalidTemplateBody(str(exc)) from exc
    return body or ""


def _get_template(db: Session, template_id: int) -> XrayTemplate:
    template = db.query(XrayTemplate).filter(XrayTemplate.id == template_id).first()
    if template is None:
        raise XrayTemplateError("template not found")
    return template


def _next_version(db: Session, template_id: int) -> int:
    current = (
        db.query(func.max(XrayTemplateVersion.version)).filter(XrayTemplateVersion.template_id == template_id).scalar()
    )
    return int(current or 0) + 1


def _append_version(db: Session, template_id: int, body: str, comment: str | None, admin) -> dict[str, Any]:
    row = XrayTemplateVersion(
        template_id=template_id,
        version=_next_version(db, template_id),
        body=body,
        comment=comment,
        author_admin_id=getattr(admin, "id", None),
        author_username=str(getattr(admin, "username", "") or ""),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    invalidate(db)
    return _version_dict(row)


def _version_dict(row: XrayTemplateVersion) -> dict[str, Any]:
    return {
        "version": row.version,
        "comment": row.comment,
        "author_username": row.author_username,
        "created_at": row.created_at,
        "size": len(row.body or ""),
    }


def list_documents(db: Session) -> list[dict[str, Any]]:
    """Документы + мета текущей версии, шаблон первым."""
    out: list[dict[str, Any]] = []
    for template in db.query(XrayTemplate).order_by(XrayTemplate.kind.desc(), XrayTemplate.id).all():
        latest = (
            db.query(XrayTemplateVersion)
            .filter(XrayTemplateVersion.template_id == template.id)
            .order_by(XrayTemplateVersion.version.desc())
            .first()
        )
        out.append(
            {
                "id": template.id,
                "kind": template.kind,
                "slug": template.slug,
                "title": template.title,
                "current": _version_dict(latest) if latest else None,
                "body": latest.body if latest else "",
                "deletable": template.kind == PROFILE_KIND and template.slug != DEFAULT_PROFILE_SLUG,
            }
        )
    return out


def list_versions(db: Session, template_id: int, limit: int, offset: int) -> list[dict[str, Any]]:
    rows = (
        db.query(XrayTemplateVersion)
        .filter(XrayTemplateVersion.template_id == template_id)
        .order_by(XrayTemplateVersion.version.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    return [_version_dict(row) for row in rows]


def get_version(db: Session, template_id: int, version: int) -> XrayTemplateVersion:
    row = (
        db.query(XrayTemplateVersion)
        .filter(XrayTemplateVersion.template_id == template_id, XrayTemplateVersion.version == version)
        .first()
    )
    if row is None:
        raise LookupError("version not found")
    return row


def save_version(db: Session, template_id: int, body: str | None, comment: str | None, admin) -> dict[str, Any]:
    _get_template(db, template_id)
    return _append_version(db, template_id, _validate(body), comment, admin)


def revert(db: Session, template_id: int, version: int, admin) -> dict[str, Any]:
    source = get_version(db, template_id, version)
    return _append_version(db, template_id, str(source.body or ""), f"откат на версию {version}", admin)


def create_profile(db: Session, slug: str, title: str, admin) -> dict[str, Any]:
    slug = (slug or "").strip()
    if not slug:
        raise XrayTemplateError("slug is required")
    if db.query(XrayTemplate).filter(XrayTemplate.slug == slug).first() is not None:
        raise XrayTemplateError("slug already exists")
    template = XrayTemplate(kind=PROFILE_KIND, slug=slug, title=(title or slug).strip())
    db.add(template)
    db.commit()
    db.refresh(template)
    _append_version(db, int(template.id), "", "создание профиля", admin)
    return {"id": template.id, "slug": template.slug, "title": template.title}


def delete_profile(db: Session, template_id: int) -> None:
    template = _get_template(db, template_id)
    if template.kind != PROFILE_KIND:
        raise XrayTemplateError("the shared template cannot be deleted")
    if template.slug == DEFAULT_PROFILE_SLUG:
        raise XrayTemplateError("the default profile cannot be deleted")
    # ON DELETE SET NULL в БД возвращает ноды на default; в ORM-сессии делаем то же
    # явно, иначе уже загруженные объекты останутся с висячим id.
    db.query(Node).filter(Node.routing_profile_id == template_id).update(
        {"routing_profile_id": None}, synchronize_session=False
    )
    db.delete(template)
    db.commit()
    invalidate(db)
