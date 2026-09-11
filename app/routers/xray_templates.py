"""REST документов клиентского конфига (общий шаблон + routing-профили) и истории версий.

Только sudo-админ. Роутер тонкий: вся логика в app.services.xray_templates (NPVPN-2024).
"""

from fastapi import APIRouter, Depends, HTTPException

from app.db import Session, get_db
from app.models.admin import Admin
from app.models.xray_template import (
    CreatedProfile,
    CreateProfilePayload,
    SaveTemplatePayload,
    XrayTemplateDocument,
    XrayTemplateVersionBody,
    XrayTemplateVersionMeta,
)
from app.services import xray_templates as service
from app.utils import responses

router = APIRouter(tags=["Settings"], prefix="/api", responses={401: responses._401})


@router.get("/settings/xray-templates", response_model=list[XrayTemplateDocument])
def list_templates(db: Session = Depends(get_db), admin: Admin = Depends(Admin.check_sudo_admin)):
    del admin
    return service.list_documents(db)


@router.get("/settings/xray-templates/{template_id}/versions", response_model=list[XrayTemplateVersionMeta])
def list_versions(
    template_id: int,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.check_sudo_admin),
):
    del admin
    return service.list_versions(db, template_id, min(limit, 200), offset)


@router.get("/settings/xray-templates/{template_id}/versions/{version}", response_model=XrayTemplateVersionBody)
def get_version(
    template_id: int,
    version: int,
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.check_sudo_admin),
):
    del admin
    try:
        row = service.get_version(db, template_id, version)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "version": row.version,
        "comment": row.comment,
        "author_username": row.author_username,
        "created_at": row.created_at,
        "size": len(row.body or ""),
        "body": row.body or "",
    }


@router.put("/settings/xray-templates/{template_id}", response_model=XrayTemplateVersionMeta)
def save_template(
    template_id: int,
    payload: SaveTemplatePayload,
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.check_sudo_admin),
):
    try:
        return service.save_version(db, template_id, payload.body, payload.comment, admin)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except service.InvalidTemplateBody as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except service.XrayTemplateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/settings/xray-templates/{template_id}/revert/{version}", response_model=XrayTemplateVersionMeta)
def revert_template(
    template_id: int,
    version: int,
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.check_sudo_admin),
):
    try:
        return service.revert(db, template_id, version, admin)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/settings/xray-templates", response_model=CreatedProfile)
def create_profile(
    payload: CreateProfilePayload,
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.check_sudo_admin),
):
    try:
        return service.create_profile(db, payload.slug, payload.title, admin)
    except service.XrayTemplateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/settings/xray-templates/{template_id}")
def delete_profile(
    template_id: int,
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.check_sudo_admin),
):
    del admin
    try:
        service.delete_profile(db, template_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except service.XrayTemplateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {}
