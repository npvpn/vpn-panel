from fastapi import APIRouter, Depends

from app.db import Session, get_db
from app.models.admin import Admin
from app.models.bot import SubscriptionProfilePayload
from app.models.settings import (
    DEFAULT_CLIENT_APPS,
    DEFAULT_PANEL_SETTINGS,
    ClientAppsPayload,
    PanelSettingsPayload,
    PanelSettingsResponse,
)
from app.services import client_apps as client_apps_service
from app.services import panel_settings as panel_settings_service
from app.services import subscription_profile as subscription_profile_service
from app.utils import responses

router = APIRouter(tags=["Settings"], prefix="/api", responses={401: responses._401})


@router.get("/settings/apps", response_model=ClientAppsPayload)
def get_client_apps(
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.get_current),
):
    del admin
    return client_apps_service.get_client_apps(db)


@router.put("/settings/apps", response_model=ClientAppsPayload)
def update_client_apps(
    payload: ClientAppsPayload,
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.get_current),
):
    del admin
    return client_apps_service.save_client_apps(db, payload)


@router.get("/settings/apps/defaults", response_model=ClientAppsPayload)
def get_default_client_apps(
    admin: Admin = Depends(Admin.get_current),
):
    del admin
    return DEFAULT_CLIENT_APPS


@router.get("/settings/panel", response_model=PanelSettingsResponse)
def get_panel_settings(
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.check_sudo_admin),
):
    del admin
    return panel_settings_service.with_primary_jwt_secret(db, panel_settings_service.get_panel_settings(db))


@router.put("/settings/panel", response_model=PanelSettingsResponse)
def update_panel_settings(
    payload: PanelSettingsPayload,
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.check_sudo_admin),
):
    del admin
    return panel_settings_service.with_primary_jwt_secret(db, panel_settings_service.save_panel_settings(db, payload))


@router.get("/settings/panel/defaults", response_model=PanelSettingsPayload)
def get_default_panel_settings(
    admin: Admin = Depends(Admin.check_sudo_admin),
):
    del admin
    return DEFAULT_PANEL_SETTINGS


@router.get("/settings/subscription", response_model=SubscriptionProfilePayload)
def get_subscription_profile(
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.check_sudo_admin),
):
    del admin
    return subscription_profile_service.get_subscription_profile(db)


@router.put("/settings/subscription", response_model=SubscriptionProfilePayload)
def update_subscription_profile(
    payload: SubscriptionProfilePayload,
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.check_sudo_admin),
):
    del admin
    return subscription_profile_service.save_subscription_profile(db, payload)
