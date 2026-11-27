from typing import Annotated
from urllib.parse import quote

import requests
from decouple import config
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, StrictBool, ValidationError

from app import logger, xray
from app.db import GetDB, Session, crud, get_db
from app.models.admin import Admin, oauth2_scheme
from app.models.bot import (
    DEFAULT_BOT_SETTINGS,
    BotAdminSyncUpdate,
    BotCreate,
    BotResponse,
    BotSettingsPayload,
    BotSettingsResponse,
    BotUpdate,
    apply_bot_settings_fallback,
)
from app.services import managed_settings as managed_svc
from app.utils import responses

router = APIRouter(tags=["Bot"], prefix="/api", responses={401: responses._401})


class BotLifecycleUpdate(BaseModel):
    is_active: StrictBool


class BotLifecycle(BotLifecycleUpdate):
    active_subscriptions: int


def _require_lifecycle_admin(token: Annotated[str, Depends(oauth2_scheme)]) -> Admin:
    with GetDB() as db:
        return Admin.check_sudo_admin(db=db, token=token)


def _bot_lifecycle(username: str, update: BotLifecycleUpdate | None = None):
    url = config("PANEL_BOT_LIFECYCLE_URL", default="").strip().rstrip("/")
    token = config("PANEL_BOT_LIFECYCLE_TOKEN", default="").strip()
    if not url or not token:
        raise HTTPException(status_code=404, detail="bot_lifecycle_unavailable")
    with GetDB() as db:
        bot = crud.get_bot(db, username)
        if bot is None or bot.source_bot_id is None:
            raise HTTPException(status_code=404, detail="bot_lifecycle_unavailable")
        username = str(bot.username)
        source_id = str(bot.source_bot_id)
    params = {"source_bot_id": source_id}
    method = "GET" if update is None else "PATCH"
    if update is not None:
        params["active"] = str(update.is_active).lower()
    try:
        response = requests.request(
            method,
            f"{url}/{quote(username, safe='')}/lifecycle",
            params=params,
            headers={"Authorization": f"Bearer {token}"},
            timeout=(3, 15),
            allow_redirects=False,
        )
        if response.status_code == 404 and response.json() == {"detail": "bot_lifecycle_unavailable"}:
            raise HTTPException(status_code=404, detail="bot_lifecycle_unavailable")
        if response.status_code == 409:
            raise HTTPException(status_code=409, detail="bot_lifecycle_busy")
        if response.status_code != 200:
            logger.warning(
                "Bot lifecycle upstream error: source_id=%s method=%s status=%s",
                source_id,
                method,
                response.status_code,
            )
            raise HTTPException(status_code=502, detail="bot_lifecycle_failed")
        model = BotLifecycle if update is None else BotLifecycleUpdate
        return model.model_validate(response.json())
    except (requests.RequestException, ValidationError) as exc:
        logger.warning(
            "Bot lifecycle request failed: source_id=%s method=%s error=%s", source_id, method, type(exc).__name__
        )
        raise HTTPException(status_code=502, detail="bot_lifecycle_failed") from exc


@router.get("/bots/{bot_username}/lifecycle", response_model=BotLifecycle)
def get_bot_lifecycle(bot_username: str, admin: Annotated[Admin, Depends(_require_lifecycle_admin)]):
    del admin
    return _bot_lifecycle(bot_username)


@router.patch("/bots/{bot_username}/lifecycle", response_model=BotLifecycleUpdate)
def update_bot_lifecycle(
    bot_username: str,
    payload: BotLifecycleUpdate,
    admin: Annotated[Admin, Depends(_require_lifecycle_admin)],
):
    del admin
    return _bot_lifecycle(bot_username, payload)


def _bot_response(db: Session, bot) -> dict:
    return {
        "id": bot.id,
        "username": bot.username,
        "title": bot.title,
        "source_bot_id": bot.source_bot_id,
        "admin_sync_enabled": bot.admin_sync_enabled,
        "managed": managed_svc.read_bot_managed_state(db, bot),
    }


@router.get("/bots", response_model=list[BotResponse])
def get_bots(
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.get_current),
):
    del admin  # explicit auth dependency
    return [_bot_response(db, bot) for bot in crud.get_bots(db)]


@router.get("/bots/default-settings", response_model=BotSettingsPayload)
def get_default_bot_settings(
    admin: Admin = Depends(Admin.check_sudo_admin),
):
    del admin
    return apply_bot_settings_fallback(DEFAULT_BOT_SETTINGS)


@router.post("/bots", response_model=BotResponse, responses={400: responses._400, 403: responses._403})
def create_bot(
    payload: BotCreate,
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.check_sudo_admin),
):
    del admin
    try:
        bot = crud.create_bot(db, payload.username, payload.title, payload.web_url)
        xray.hosts.update()
        return _bot_response(db, bot)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))


@router.delete("/bots/{bot_username}", responses={403: responses._403, 404: responses._404})
def delete_bot(
    bot_username: str,
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.check_sudo_admin),
):
    del admin
    bot = crud.get_bot(db, bot_username)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    crud.delete_bot(db, bot)
    xray.hosts.update()
    return {"detail": "Bot deleted"}


@router.patch(
    "/bots/{bot_username}",
    response_model=BotResponse,
    responses={400: responses._400, 403: responses._403, 404: responses._404},
)
def update_bot(
    bot_username: str,
    payload: BotUpdate,
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.check_sudo_admin),
):
    del admin
    bot = crud.get_bot(db, bot_username)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    try:
        managed_svc.ensure_bot_identity_update_allowed(
            db,
            bot,
            username=payload.username,
            title=payload.title,
            web_url=payload.web_url,
        )
        updated_bot = crud.update_bot(db, bot, payload.username, payload.title, payload.web_url)
    except managed_svc.ManagedFieldChangeError:
        raise HTTPException(status_code=409, detail="managed_by_admin")
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))
    xray.hosts.update()
    return _bot_response(db, updated_bot)


@router.patch(
    "/bots/{bot_username}/admin-sync",
    response_model=BotResponse,
    responses={403: responses._403, 404: responses._404},
)
def update_bot_admin_sync(
    bot_username: str,
    payload: BotAdminSyncUpdate,
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.check_sudo_admin),
):
    del admin
    bot = crud.get_bot(db, bot_username)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    managed_svc.set_bot_admin_sync(db, bot, payload.enabled)
    return _bot_response(db, bot)


@router.get(
    "/bots/{bot_username}/settings",
    response_model=BotSettingsResponse,
    responses={403: responses._403, 404: responses._404},
)
def get_bot_settings(
    bot_username: str,
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.check_sudo_admin),
):
    del admin
    bot = crud.get_bot(db, bot_username)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    result = apply_bot_settings_fallback(crud.get_bot_settings(db, bot))
    result["managed"] = managed_svc.read_bot_managed_state(db, bot)
    return result


@router.put(
    "/bots/{bot_username}/settings",
    response_model=BotSettingsResponse,
    responses={403: responses._403, 404: responses._404},
)
def update_bot_settings(
    bot_username: str,
    payload: BotSettingsPayload,
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.check_sudo_admin),
):
    del admin
    bot = crud.get_bot(db, bot_username)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    data = payload.model_dump()
    try:
        managed_svc.ensure_bot_settings_update_allowed(db, bot, data)
    except managed_svc.ManagedFieldChangeError:
        raise HTTPException(status_code=409, detail="managed_by_admin")
    updated = crud.update_bot_settings(db, bot, data)
    result = apply_bot_settings_fallback(updated)
    result["managed"] = managed_svc.read_bot_managed_state(db, bot)
    return result
