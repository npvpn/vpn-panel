from fastapi import APIRouter, Depends, HTTPException

from app.db import Session, crud, get_db
from app.models.admin import Admin
from app.models.settings import (
    CLIENT_APPS_KEY,
    DEFAULT_CLIENT_APPS,
    DEFAULT_PANEL_SETTINGS,
    ClientAppsPayload,
    ClientAppsWithManagedResponse,
    PanelSettingsPayload,
)
from app.services import client_apps as client_apps_service
from app.services import managed_settings as managed_svc
from app.services import panel_settings as panel_settings_service
from app.utils import responses

router = APIRouter(tags=["Settings"], prefix="/api", responses={401: responses._401})


@router.get("/settings/apps", response_model=ClientAppsWithManagedResponse)
def get_client_apps(
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.get_current),
):
    del admin
    payload = client_apps_service.get_client_apps(db)
    payload["managed"] = managed_svc.read_managed_state(db, CLIENT_APPS_KEY)
    return payload


@router.put("/settings/apps", response_model=ClientAppsPayload)
def update_client_apps(
    payload: ClientAppsPayload,
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.get_current),
):
    del admin
    if crud.is_managed(db, CLIENT_APPS_KEY):
        raise HTTPException(status_code=409, detail="managed_by_admin")
    return client_apps_service.save_client_apps(db, payload)


@router.get("/settings/apps/defaults", response_model=ClientAppsPayload)
def get_default_client_apps(
    admin: Admin = Depends(Admin.get_current),
):
    del admin
    return DEFAULT_CLIENT_APPS


@router.get("/settings/panel", response_model=PanelSettingsPayload)
def get_panel_settings(
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.check_sudo_admin),
):
    del admin
    return panel_settings_service.get_panel_settings(db)


@router.put("/settings/panel", response_model=PanelSettingsPayload)
def update_panel_settings(
    payload: PanelSettingsPayload,
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.check_sudo_admin),
):
    del admin
    return panel_settings_service.save_panel_settings(db, payload)


@router.get("/settings/panel/defaults", response_model=PanelSettingsPayload)
def get_default_panel_settings(
    admin: Admin = Depends(Admin.check_sudo_admin),
):
    del admin
    return DEFAULT_PANEL_SETTINGS
