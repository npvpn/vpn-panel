"""Документы клиентского конфига и их версии (NPVPN-2024).

Append-only: активная редакция — версия с максимальным номером.
"""

from __future__ import annotations

from functools import cache
from typing import Any, cast

from sqlalchemy import func

from app.db import GetDB, Session
from app.db.models import (
    DEFAULT_CONFIG_SLUG,
    ProxyHost,
    XrayTemplate,
    XrayTemplateVersion,
)
from app.models.host_injection import (
    InjectionDiagnostic,
    InjectionPreview,
    InjectionPreviewHost,
    InjectionPreviewRequest,
)
from app.xray.client_configs import parse_json_object
from app.xray.host_injection import template_injection

_SESSION_CACHE_KEY = "_xray_templates"


def get_active_bodies(db: Session) -> dict[str, Any]:
    """{"configs": {id: body}, "default_id": int | None}.

    Документы самодостаточны (NPVPN-2024): каждое тело — ПОЛНЫЙ клиентский конфиг,
    видов документов больше нет. В "configs" попадают только НЕпустые тела: пустое
    тело означает «документ не заполнен», и рендер уходит фолбэком на дефолтный
    документ (см. app.xray.client_configs.select_config).

    "default_id" — id документа со slug `default`; он вторая ступень фолбэка и
    отдаётся отдельно именно потому, что при пустом теле в "configs" его нет.

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
        db.query(XrayTemplate.id, XrayTemplate.slug, XrayTemplateVersion.body)
        .join(XrayTemplateVersion, XrayTemplateVersion.template_id == XrayTemplate.id)
        .join(
            latest,
            (latest.c.template_id == XrayTemplateVersion.template_id)
            & (latest.c.max_version == XrayTemplateVersion.version),
        )
        .all()
    )
    bodies: dict[str, Any] = {"configs": {}, "default_id": None}
    for template_id, slug, body in rows:
        if slug == DEFAULT_CONFIG_SLUG:
            bodies["default_id"] = template_id
        if (body or "").strip():
            bodies["configs"][template_id] = body
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
        document = parse_json_object(body)
        if document is not None:
            template_injection(document)
    except ValueError as exc:
        raise InvalidTemplateBody(str(exc)) from exc
    return body or ""


def _get_template(db: Session, template_id: int) -> XrayTemplate:
    template = db.query(XrayTemplate).filter(XrayTemplate.id == template_id).first()
    if template is None:
        # LookupError, а не XrayTemplateError: «документа нет» — это 404, а не 409
        # (409 остаётся за нарушением правил: дубль slug, удаление неудаляемого).
        raise LookupError("template not found")
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
    """Документы + мета текущей версии, в порядке создания."""
    out: list[dict[str, Any]] = []
    lookup = build_template_lookup(get_active_bodies(db))
    for template in db.query(XrayTemplate).order_by(XrayTemplate.id).all():
        latest = (
            db.query(XrayTemplateVersion)
            .filter(XrayTemplateVersion.template_id == template.id)
            .order_by(XrayTemplateVersion.version.desc())
            .first()
        )
        injection = None
        injection_error = False
        try:
            resolved = template_injection(lookup(template.id))
            injection = resolved.model_dump(mode="json") if resolved else None
        except ValueError:
            # An invalid historical document must remain editable in the UI.
            injection_error = True
        out.append(
            {
                "effective_injection": injection,
                "effective_injection_error": injection_error,
                "id": template.id,
                "slug": template.slug,
                "title": template.title,
                "current": _version_dict(latest) if latest else None,
                "body": latest.body if latest else "",
                "deletable": template.slug != DEFAULT_CONFIG_SLUG,
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
    return _append_version(db, template_id, _validate(str(source.body or "")), f"откат на версию {version}", admin)


def _default_body(db: Session) -> str:
    """Тело дефолтного конфига, а при пустом — файловый шаблон.

    Новый документ обязан рождаться рабочим: пустой самодостаточный конфиг
    молча уехал бы на фолбэк и выглядел бы как «конфиг не применяется».
    """
    row = db.query(XrayTemplate).filter(XrayTemplate.slug == DEFAULT_CONFIG_SLUG).first()
    if row is not None:
        latest = (
            db.query(XrayTemplateVersion)
            .filter(XrayTemplateVersion.template_id == row.id)
            .order_by(XrayTemplateVersion.version.desc())
            .first()
        )
        if latest is not None and (latest.body or "").strip():
            return str(latest.body)
    from app.templates import render_template
    from config import V2RAY_SUBSCRIPTION_TEMPLATE

    return render_template(V2RAY_SUBSCRIPTION_TEMPLATE)


def create_config(db: Session, slug: str, title: str, admin) -> dict[str, Any]:
    slug = (slug or "").strip()
    if not slug:
        raise XrayTemplateError("slug is required")
    if db.query(XrayTemplate).filter(XrayTemplate.slug == slug).first() is not None:
        raise XrayTemplateError("slug already exists")
    template = XrayTemplate(slug=slug, title=(title or slug).strip())
    db.add(template)
    db.commit()
    db.refresh(template)
    _append_version(db, int(template.id), _default_body(db), "создан копией дефолтного конфига", admin)
    return {"id": template.id, "slug": template.slug, "title": template.title}


def assert_config_exists(db: Session, template_id: int | None) -> None:
    """None (документ default) допустим; иначе id обязан быть существующим документом."""
    if template_id is None:
        return
    if db.query(XrayTemplate).filter(XrayTemplate.id == template_id).first() is None:
        raise XrayTemplateError("unknown client config")


def delete_config(db: Session, template_id: int) -> None:
    template = _get_template(db, template_id)
    if template.slug == DEFAULT_CONFIG_SLUG:
        raise XrayTemplateError("the default config cannot be deleted")
    # ON DELETE SET NULL в БД возвращает хосты на default (NPVPN-2024: привязка живёт
    # на ProxyHost, а не на Node); в ORM-сессии делаем то же явно, иначе уже
    # загруженные объекты останутся с висячим id.
    db.query(ProxyHost).filter(ProxyHost.client_config_id == template_id).update(
        {"client_config_id": None}, synchronize_session=False
    )
    db.delete(template)
    db.commit()
    invalidate(db)


def build_template_lookup(bodies):
    """Парсинг один раз на операцию; ошибочный документ не заменяется рабочим default."""
    from app.templates import render_template
    from app.xray.client_configs import make_template_lookup
    from config import V2RAY_SUBSCRIPTION_TEMPLATE

    configs = {}
    for id_, raw in bodies.get("configs", {}).items():
        try:
            body = parse_json_object(raw)
        except ValueError:
            body = {"npvpn": None}
        if body is not None:
            configs[id_] = body
    return make_template_lookup(configs, bodies.get("default_id"), lambda: render_template(V2RAY_SUBSCRIPTION_TEMPLATE))


def composition_classifier(db: Session):
    """Пакетный источник истины для pins и снимков, включая default/file template."""
    from app.xray.host_injection import resolve_host_injection

    lookup = build_template_lookup(get_active_bodies(db))

    def is_composite(host):
        try:
            return resolve_host_injection(host.host_injection, lookup(host.client_config_id)) is not None
        except ValueError:
            return True  # Invalid composition cannot be pinned or reconstructed as an ordinary host.

    return is_composite


def preview_injection(db: Session, request: InjectionPreviewRequest, active_inbounds: set[str]) -> InjectionPreview:
    """Sudo-only draft preview; no ORM mutation, commit or cache invalidation."""
    from app.xray.host_injection import diagnose_injection

    bodies = get_active_bodies(db)
    if request.template_body is not None:
        try:
            parse_json_object(request.template_body)
        except ValueError:
            return InjectionPreview(issues=[InjectionDiagnostic(code="invalid_template", level="error")])
        if request.recipient.client_config_id is None:
            return InjectionPreview(issues=[InjectionDiagnostic(code="missing_template", level="error")])
        bodies = {**bodies, "configs": {**bodies["configs"], request.recipient.client_config_id: request.template_body}}
    lookup = build_template_lookup(bodies)
    fields = InjectionPreviewHost.model_fields
    catalog = {cast(int, host.id): {key: getattr(host, key) for key in fields} for host in db.query(ProxyHost).all()}
    for excluded_id in request.excluded_host_ids:
        catalog.pop(excluded_id, None)
    for draft in request.hosts:
        if draft.id is not None and draft.id in catalog:
            catalog[draft.id].update(draft.model_dump(exclude_unset=True))
    recipient = request.recipient.model_dump()
    if request.recipient.id is not None and request.recipient.id in catalog:
        recipient = {**catalog[request.recipient.id], **request.recipient.model_dump(exclude_unset=True)}
        catalog[request.recipient.id] = recipient
    result = diagnose_injection(recipient, list(catalog.values()), lookup, active_inbounds)
    if request.template_body is not None and recipient["host_injection"] is not None:
        result.issues.insert(0, InjectionDiagnostic(code="form_override"))
    return result
