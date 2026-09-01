import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import cast
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app import logger, xray
from app.db import Session, crud, get_db
from app.db.models import Proxy as DBProxy
from app.db.models import User as DBUser
from app.dependencies import get_expired_users_list, get_validated_user, validate_dates
from app.models.admin import Admin
from app.models.proxy import (
    ProxyTypes,
    ShadowsocksSettings,
    TrojanSettings,
    VLESSSettings,
    VMessSettings,
    XTLSFlows,
)
from app.models.user import (
    UserBsExtraModify,
    UserBsTrafficResponse,
    UserCreate,
    UserDeviceCreate,
    UserDeviceResponse,
    UserDevicesResponse,
    UserDeviceUpdate,
    UserModify,
    UserResponse,
    UsersDigestResponse,
    UsersResponse,
    UserStatus,
    UsersUsagesResponse,
    UserUsagesResponse,
)
from app.subscription.bot_settings import resolve_bot_settings
from app.utils import report, responses
from app.utils.request_context import request_id_var
from config import SYNC_INBOUNDS_DB_CHUNK_SIZE, SYNC_INBOUNDS_MAX_CONCURRENCY

router = APIRouter(tags=["User"], prefix="/api", responses={401: responses._401})

SYNC_PROGRESS = {}

# Dedicated executor for sync-inbounds workers. We intentionally do NOT reuse
# the shared xray thread pool: at scale we would queue thousands of sync
# tasks there and starve every other xray operation (user CRUD, node restarts,
# periodic update_user_by_id) of worker threads. With its own pool, sync's
# concurrency is hard-bounded and independent.
_SYNC_EXECUTOR: ThreadPoolExecutor | None = None
_SYNC_EXECUTOR_LOCK = threading.Lock()


def _get_sync_executor() -> ThreadPoolExecutor:
    global _SYNC_EXECUTOR
    if _SYNC_EXECUTOR is None:
        with _SYNC_EXECUTOR_LOCK:
            if _SYNC_EXECUTOR is None:
                _SYNC_EXECUTOR = ThreadPoolExecutor(
                    max_workers=max(1, SYNC_INBOUNDS_MAX_CONCURRENCY),
                    thread_name_prefix="sync-inbounds",
                )
    return _SYNC_EXECUTOR


def _update_single_user(user_id: int) -> bool:
    """Refresh a user on running xray cores.

    DB session is opened only long enough to load and detach the user graph
    (proxies + excluded_inbounds), then closed before any gRPC calls. This
    keeps DB connections out of the pool for the full duration of potentially
    slow node round-trips.
    """
    from app.db import GetDB

    with GetDB() as db:
        dbuser = (
            db.query(DBUser)
            .options(
                selectinload(DBUser.proxies).selectinload(DBProxy.excluded_inbounds),
            )
            .filter(DBUser.id == user_id)
            .first()
        )
        if not dbuser:
            return False
        db.expunge(dbuser)
    xray.operations.update_user(dbuser)
    return True


def _bump_progress(op_id: str, field: str, delta: int = 1):
    st = SYNC_PROGRESS.get(op_id)
    if not st:
        return
    st[field] = st.get(field, 0) + delta


def _mark_finished(op_id: str):
    st = SYNC_PROGRESS.get(op_id)
    if not st:
        return
    st["running"] = False
    st["finished_at"] = datetime.utcnow().isoformat()


def _batch_sync_users(user_ids: list, op_id: str):
    """Process user updates via the dedicated sync executor.

    Submits a bounded sliding window so we never queue thousands of pending
    tasks; each in-flight task maps 1:1 to a DB connection + gRPC round-trip.
    """
    executor = _get_sync_executor()
    total = len(user_ids)
    window = max(1, SYNC_INBOUNDS_MAX_CONCURRENCY) * 2

    pending: dict = {}
    idx = 0

    def _on_done(uid: int, fut):
        try:
            fut.result()
        except Exception as e:
            logger.warning("[sync-inbounds] failed to update user_id=%d: %s", uid, e)
        finally:
            try:
                st = SYNC_PROGRESS.get(op_id)
                if st:
                    st["done"] = st.get("done", 0) + 1
                    if st["done"] >= st.get("scheduled", 0):
                        _mark_finished(op_id)
            except Exception:
                pass

    while idx < total or pending:
        while idx < total and len(pending) < window:
            uid = user_ids[idx]
            pending[executor.submit(_update_single_user, uid)] = uid
            idx += 1

        for future in as_completed(list(pending.keys())):
            uid = pending.pop(future)
            _on_done(uid, future)
            break  # refill window immediately


@router.post("/user", response_model=UserResponse, responses={400: responses._400, 409: responses._409})
def add_user(
    new_user: UserCreate,
    bg: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.get_current),
):
    """
    Add a new user

    - **username**: 3 to 32 characters, can include a-z, 0-9, and underscores.
    - **status**: User's status, defaults to `active`. Special rules if `on_hold`.
    - **expire**: UTC timestamp for account expiration. Use `0` for unlimited.
    - **data_limit**: Max data usage in bytes (e.g., `1073741824` for 1GB). `0` means unlimited.
    - **data_limit_reset_strategy**: Defines how/if data limit resets. `no_reset` means it never resets.
    - **proxies**: Dictionary of protocol settings (e.g., `vmess`, `vless`).
    - **inbounds**: Dictionary of protocol tags to specify inbound connections.
    - **note**: Optional text field for additional user information or notes.
    - **on_hold_timeout**: UTC timestamp when `on_hold` status should start or end.
    - **on_hold_expire_duration**: Duration (in seconds) for how long the user should stay in `on_hold` status.
    - **next_plan**: Next user plan (resets after use).
    """

    # TODO expire should be datetime instead of timestamp

    for proxy_type in new_user.proxies:
        if not xray.config.inbounds_by_protocol.get(proxy_type):
            raise HTTPException(
                status_code=400,
                detail=f"Protocol {proxy_type} is disabled on your server",
            )

    try:
        _t0 = time.monotonic()
        dbuser = crud.create_user(db, new_user, admin=crud.get_admin(db, admin.username))
        _dur_ms = int((time.monotonic() - _t0) * 1000)
        if _dur_ms >= 500:
            logger.warning(
                "[user.add.slow] username=%s dur_ms=%d rid=%s",
                getattr(dbuser, "username", "-"),
                _dur_ms,
                request_id_var.get() or "-",
            )
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="User already exists")
    except ValueError as err:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(err))

    bg.add_task(xray.operations.add_user, dbuser=dbuser)
    user = UserResponse.model_validate(dbuser)
    report.user_created(user=user, user_id=dbuser.id, by=admin, user_admin=dbuser.admin)
    logger.info(f'New user "{dbuser.username}" added')
    return user


@router.get("/user/{username}", response_model=UserResponse, responses={403: responses._403, 404: responses._404})
def get_user(
    request: Request,
    db: Session = Depends(get_db),
    dbuser: UserResponse = Depends(get_validated_user),
):
    """Get user information"""
    _t0 = time.monotonic()
    _t_ensure0 = time.monotonic()
    crud.ensure_subscription_token(db, dbuser)
    _ensure_ms = int((time.monotonic() - _t_ensure0) * 1000)

    _t_ser0 = time.monotonic()
    resp = UserResponse.model_validate(dbuser)
    _ser_ms = int((time.monotonic() - _t_ser0) * 1000)

    _total_ms = int((time.monotonic() - _t0) * 1000)
    if _total_ms >= 500 or _ensure_ms >= 200 or _ser_ms >= 200:
        logger.warning(
            "[user.get.slow] username=%s total_ms=%d ensure_ms=%d serialize_ms=%d rid=%s",
            getattr(dbuser, "username", "-"),
            _total_ms,
            _ensure_ms,
            _ser_ms,
            request_id_var.get() or "-",
        )
    return resp


@router.get(
    "/user/{username}/devices",
    response_model=UserDevicesResponse,
    responses={403: responses._403, 404: responses._404},
)
def list_user_devices(
    dbuser: UserResponse = Depends(get_validated_user),
    db: Session = Depends(get_db),
):
    devices = crud.get_user_devices(db, dbuser)
    return {"devices": devices}


@router.post(
    "/user/{username}/devices",
    response_model=UserDeviceResponse,
    responses={400: responses._400, 403: responses._403, 404: responses._404, 409: responses._409},
)
def add_user_device(
    device: UserDeviceCreate,
    dbuser: UserResponse = Depends(get_validated_user),
    db: Session = Depends(get_db),
):
    hard_mode = bool(resolve_bot_settings(cast(DBUser, dbuser)).get("sub_device_limit_hard_mode"))
    if hard_mode and dbuser.device_limit and crud.count_user_devices(db, dbuser) >= dbuser.device_limit:
        raise HTTPException(status_code=403, detail="Device limit reached")
    try:
        dbdevice = crud.create_user_device(db, dbuser, device)
    except IntegrityError:
        raise HTTPException(status_code=409, detail="Device already exists")
    return dbdevice


@router.put(
    "/user/{username}/devices/{device_id}",
    response_model=UserDeviceResponse,
    responses={400: responses._400, 403: responses._403, 404: responses._404, 409: responses._409},
)
def update_user_device(
    device_id: int,
    device: UserDeviceUpdate,
    dbuser: UserResponse = Depends(get_validated_user),
    db: Session = Depends(get_db),
):
    dbdevice = crud.get_user_device(db, dbuser, device_id)
    if not dbdevice:
        raise HTTPException(status_code=404, detail="Device not found")
    if device.hwid:
        existing = crud.get_user_device_by_hwid(db, dbuser, device.hwid)
        if existing and existing.id != dbdevice.id:
            raise HTTPException(status_code=409, detail="Device already exists")
    try:
        return crud.update_user_device(db, dbdevice, device)
    except IntegrityError:
        raise HTTPException(status_code=409, detail="Device already exists")


@router.delete(
    "/user/{username}/devices/{device_id}",
    responses={403: responses._403, 404: responses._404},
)
def delete_user_device(
    device_id: int,
    dbuser: UserResponse = Depends(get_validated_user),
    db: Session = Depends(get_db),
):
    dbdevice = crud.get_user_device(db, dbuser, device_id)
    if not dbdevice:
        raise HTTPException(status_code=404, detail="Device not found")
    crud.delete_user_device(db, dbdevice)
    return {"detail": "Device successfully deleted"}


@router.put(
    "/user/{username}",
    response_model=UserResponse,
    responses={400: responses._400, 403: responses._403, 404: responses._404},
)
def modify_user(
    modified_user: UserModify,
    bg: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db),
    dbuser: UsersResponse = Depends(get_validated_user),
    admin: Admin = Depends(Admin.get_current),
):
    """
    Modify an existing user

    - **username**: Cannot be changed. Used to identify the user.
    - **status**: User's new status. Can be 'active', 'disabled', 'on_hold', 'limited', or 'expired'.
    - **expire**: UTC timestamp for new account expiration. Set to `0` for unlimited, `null` for no change.
    - **data_limit**: New max data usage in bytes (e.g., `1073741824` for 1GB). Set to `0` for unlimited, `null` for no change.
    - **data_limit_reset_strategy**: New strategy for data limit reset. Options include 'daily', 'weekly', 'monthly', or 'no_reset'.
    - **proxies**: Dictionary of new protocol settings (e.g., `vmess`, `vless`). Empty dictionary means no change.
    - **inbounds**: Dictionary of new protocol tags to specify inbound connections. Empty dictionary means no change.
    - **note**: New optional text for additional user information or notes. `null` means no change.
    - **on_hold_timeout**: New UTC timestamp for when `on_hold` status should start or end. Only applicable if status is changed to 'on_hold'.
    - **on_hold_expire_duration**: New duration (in seconds) for how long the user should stay in `on_hold` status. Only applicable if status is changed to 'on_hold'.
    - **next_plan**: Next user plan (resets after use).

    Note: Fields set to `null` or omitted will not be modified.
    """

    for proxy_type in modified_user.proxies:
        if not xray.config.inbounds_by_protocol.get(proxy_type):
            raise HTTPException(
                status_code=400,
                detail=f"Protocol {proxy_type} is disabled on your server",
            )

    old_status = dbuser.status
    _t0 = time.monotonic()
    try:
        dbuser = crud.update_user(db, dbuser, modified_user)
    except ValueError as err:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(err))
    _dur_ms = int((time.monotonic() - _t0) * 1000)
    if _dur_ms >= 500:
        logger.warning(
            "[user.modify.slow] username=%s dur_ms=%d rid=%s",
            getattr(dbuser, "username", "-"),
            _dur_ms,
            request_id_var.get() or "-",
        )
    user = UserResponse.model_validate(dbuser)

    if user.status in [UserStatus.active, UserStatus.on_hold]:
        bg.add_task(xray.operations.update_user, dbuser=dbuser)
    else:
        bg.add_task(xray.operations.remove_user, dbuser=dbuser)

    bg.add_task(report.user_updated, user=user, user_admin=dbuser.admin, by=admin)

    logger.info(f'User "{user.username}" modified')

    if user.status != old_status:
        bg.add_task(
            report.status_change,
            username=user.username,
            status=user.status,
            user=user,
            user_admin=dbuser.admin,
            by=admin,
        )
        logger.info(f'User "{dbuser.username}" status changed from {old_status} to {user.status}')

    return user


@router.delete("/user/{username}", responses={403: responses._403, 404: responses._404})
def remove_user(
    bg: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db),
    dbuser: UserResponse = Depends(get_validated_user),
    admin: Admin = Depends(Admin.get_current),
):
    """Remove a user"""
    _t0 = time.monotonic()
    crud.remove_user(db, dbuser)
    _dur_ms = int((time.monotonic() - _t0) * 1000)
    if _dur_ms >= 500:
        logger.warning(
            "[user.delete.slow] username=%s dur_ms=%d rid=%s",
            getattr(dbuser, "username", "-"),
            _dur_ms,
            request_id_var.get() or "-",
        )
    bg.add_task(xray.operations.remove_user, dbuser=dbuser)

    bg.add_task(report.user_deleted, username=dbuser.username, user_admin=Admin.model_validate(dbuser.admin), by=admin)

    logger.info(f'User "{dbuser.username}" deleted')
    return {"detail": "User successfully deleted"}


@router.post(
    "/user/{username}/reset", response_model=UserResponse, responses={403: responses._403, 404: responses._404}
)
def reset_user_data_usage(
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    dbuser: UserResponse = Depends(get_validated_user),
    admin: Admin = Depends(Admin.get_current),
):
    """Reset user data usage"""
    dbuser = crud.reset_user_data_usage(db=db, dbuser=dbuser)
    if dbuser.status in [UserStatus.active, UserStatus.on_hold]:
        bg.add_task(xray.operations.add_user, dbuser=dbuser)

    user = UserResponse.model_validate(dbuser)
    bg.add_task(report.user_data_usage_reset, user=user, user_admin=dbuser.admin, by=admin)

    logger.info(f'User "{dbuser.username}"\'s usage was reset')
    return dbuser


@router.post(
    "/user/{username}/revoke_sub", response_model=UserResponse, responses={403: responses._403, 404: responses._404}
)
def revoke_user_subscription(
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    dbuser: UserResponse = Depends(get_validated_user),
    admin: Admin = Depends(Admin.get_current),
):
    """Revoke users subscription (Subscription link and proxies)"""
    dbuser = crud.revoke_user_sub(db=db, dbuser=dbuser)

    if dbuser.status in [UserStatus.active, UserStatus.on_hold]:
        bg.add_task(xray.operations.update_user, dbuser=dbuser)
    user = UserResponse.model_validate(dbuser)
    bg.add_task(report.user_subscription_revoked, user=user, user_admin=dbuser.admin, by=admin)

    logger.info(f'User "{dbuser.username}" subscription revoked')

    return user


@router.get(
    "/users", response_model=UsersResponse, responses={400: responses._400, 403: responses._403, 404: responses._404}
)
def get_users(
    offset: int = None,
    limit: int = None,
    username: list[str] = Query(None),
    search: str | None = None,
    owner: list[str] | None = Query(None, alias="admin"),
    bot_username: str | None = None,
    status: UserStatus = None,
    sort: str = None,
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.get_current),
):
    """Get all users"""
    if sort is not None:
        opts = sort.strip(",").split(",")
        sort = []
        for opt in opts:
            try:
                sort.append(crud.UsersSortingOptions[opt])
            except KeyError:
                raise HTTPException(status_code=400, detail=f'"{opt}" is not a valid sort option')

    users, count = crud.get_users(
        db=db,
        offset=offset,
        limit=limit,
        search=search,
        bot_username=bot_username,
        usernames=username,
        status=status,
        sort=sort,
        admins=owner if admin.is_sudo else [admin.username],
        return_with_count=True,
    )
    # Ensure tokens for legacy users to populate subscription_url in UI
    for u in users:
        crud.ensure_subscription_token(db, u)
    return {"users": users, "total": count}


@router.get(
    "/users/digest",
    response_model=UsersDigestResponse,
    responses={403: responses._403},
)
def get_users_digest_endpoint(
    offset: int = None,
    limit: int = None,
    bot_username: str | None = None,
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.get_current),
):
    """Лёгкий срез {username, status, expire} для сверки с ботом (NPVPN-1643)."""
    from app.services.user_digest import get_users_digest

    users, total = get_users_digest(
        db,
        admins=None if admin.is_sudo else [admin.username],
        bot_username=bot_username,
        offset=offset,
        limit=limit,
    )
    return {"users": users, "total": total}


@router.post("/users/reset", responses={403: responses._403, 404: responses._404})
def reset_users_data_usage(db: Session = Depends(get_db), admin: Admin = Depends(Admin.check_sudo_admin)):
    """Reset all users data usage"""
    dbadmin = crud.get_admin(db, admin.username)
    crud.reset_all_users_data_usage(db=db, admin=dbadmin)
    startup_config = xray.config.include_db_users()
    xray.core.restart(startup_config)
    for node_id, node in list(xray.nodes.items()):
        if node.connected:
            xray.operations.restart_node(node_id, startup_config)
    return {"detail": "Users successfully reset."}


def _reconcile_user_inbounds(dbuser) -> bool:
    """Apply global-config reconciliation to a single user in-place.

    Returns True when the user was modified (needs DB flush)."""
    changed = False

    try:
        existing_types = {p.type for p in dbuser.proxies}
    except Exception:
        existing_types = set()
    global_protocols = [ProxyTypes(p) for p, inbounds in xray.config.inbounds_by_protocol.items() if inbounds]
    missing_protocols = [p for p in global_protocols if p not in existing_types]
    for protocol in missing_protocols:
        if protocol == ProxyTypes.VLESS:
            settings = VLESSSettings(flow=XTLSFlows.VISION)
        elif protocol == ProxyTypes.VMess:
            settings = VMessSettings()
        elif protocol == ProxyTypes.Shadowsocks:
            settings = ShadowsocksSettings()
        elif protocol == ProxyTypes.Trojan:
            settings = TrojanSettings()
        else:
            continue

        dbuser.proxies.append(DBProxy(type=protocol, settings=settings.dict(no_obj=True)))
        changed = True
        logger.info('[sync-inbounds] added missing protocol=%s for user="%s"', protocol.value, dbuser.username)

    for proxy in dbuser.proxies:
        global_inbounds = xray.config.inbounds_by_protocol.get(
            proxy.type if isinstance(proxy.type, str) else proxy.type.value, []
        )
        global_tags = {i["tag"] for i in global_inbounds}

        if proxy.excluded_inbounds:
            before_count = len(proxy.excluded_inbounds)
            filtered_exclusions = [inbound for inbound in proxy.excluded_inbounds if inbound.tag in global_tags]
            cleared = bool(filtered_exclusions)
            if filtered_exclusions:
                proxy.excluded_inbounds = []
            changed = True
            logger.info(
                "[sync-inbounds] user=%s protocol=%s excl_before=%d global_tags=%d cleared=%s",
                dbuser.username,
                str(proxy.type),
                before_count,
                len(global_tags),
                str(cleared),
            )

    return changed


def _run_sync_inbounds(op_id: str):
    """Full sync driver: runs in BG so the HTTP request returns immediately.

    Iterates active users in chunks, each chunk uses its own short-lived DB
    session so no single connection is held for the whole sweep. Runtime
    updates are then scheduled through the xray thread pool, where
    _update_single_user releases DB connections before doing gRPC.
    """
    from app.db import GetDB

    try:
        with GetDB() as db:
            active_user_ids = [uid for (uid,) in db.query(DBUser.id).filter(DBUser.status == UserStatus.active).all()]
        total = len(active_user_ids)
        st = SYNC_PROGRESS.get(op_id)
        if st is not None:
            st["total"] = total
        logger.info("[sync-inbounds] op_id=%s active_users=%d", op_id, total)

        users_updated = 0
        scheduled_user_ids: list[int] = []

        for chunk_start in range(0, total, SYNC_INBOUNDS_DB_CHUNK_SIZE):
            chunk_ids = active_user_ids[chunk_start : chunk_start + SYNC_INBOUNDS_DB_CHUNK_SIZE]
            with GetDB() as db:
                chunk_users = (
                    db.query(DBUser)
                    .options(selectinload(DBUser.proxies).selectinload(DBProxy.excluded_inbounds))
                    .filter(DBUser.id.in_(chunk_ids))
                    .all()
                )
                chunk_changed = 0
                for dbuser in chunk_users:
                    if _reconcile_user_inbounds(dbuser):
                        chunk_changed += 1
                    if dbuser.status in (UserStatus.active, UserStatus.on_hold):
                        scheduled_user_ids.append(dbuser.id)
                    _bump_progress(op_id, "users_processed", 1)
                if chunk_changed:
                    db.commit()
                    users_updated += chunk_changed

        users_scheduled = len(scheduled_user_ids)
        st = SYNC_PROGRESS.get(op_id)
        if st is not None:
            st["users_updated"] = users_updated
            st["scheduled"] = users_scheduled

        logger.info(
            "[sync-inbounds] op_id=%s db_phase_done updated=%d scheduled=%d",
            op_id,
            users_updated,
            users_scheduled,
        )

        if scheduled_user_ids:
            _batch_sync_users(scheduled_user_ids, op_id)
        else:
            _mark_finished(op_id)
    except Exception as e:
        logger.exception("[sync-inbounds] op_id=%s failed: %s", op_id, e)
        st = SYNC_PROGRESS.get(op_id)
        if st is not None:
            st["error"] = str(e)
        _mark_finished(op_id)


@router.post("/users/sync-inbounds", responses={403: responses._403})
def sync_users_inbounds(
    bg: BackgroundTasks,
    admin: Admin = Depends(Admin.check_sudo_admin),
):
    """
    Sync active users' inbounds with the global XRay configuration.
    Returns immediately; progress is tracked via `/users/sync-inbounds/status`.
    """
    logger.info("[sync-inbounds] started by %s", admin.username)
    op_id = uuid4().hex
    SYNC_PROGRESS[op_id] = {
        "running": True,
        "started_at": datetime.utcnow().isoformat(),
        "users_processed": 0,
        "users_updated": 0,
        "scheduled": 0,
        "done": 0,
        "total": 0,
        "by": admin.username,
    }

    # Offload the entire sweep (DB reconciliation + gRPC fan-out) so this
    # HTTP handler does not keep any DB connection for the duration of the
    # operation. Subscription endpoints keep serving normally.
    bg.add_task(_run_sync_inbounds, op_id=op_id)

    return {
        "detail": "Sync scheduled.",
        "op_id": op_id,
    }


@router.get("/users/sync-inbounds/status")
def get_sync_inbounds_status(op_id: str = None, admin: Admin = Depends(Admin.get_current)):
    """
    Returns status of a sync operation. If op_id is not provided, returns the latest one for this admin (if any).
    """
    if not SYNC_PROGRESS:
        return {"detail": "no sync running"}
    if not op_id:
        # pick latest entry for this admin
        latest = None
        for k, v in SYNC_PROGRESS.items():
            if v.get("by") != admin.username:
                continue
            if latest is None or v.get("started_at", "") > SYNC_PROGRESS[latest].get("started_at", ""):
                latest = k
        if not latest:
            return {"detail": "no sync found for this admin"}
        op_id = latest
    st = SYNC_PROGRESS.get(op_id)
    if not st:
        return {"detail": "not found"}
    return {"op_id": op_id, **st}


@router.get(
    "/user/{username}/usage", response_model=UserUsagesResponse, responses={403: responses._403, 404: responses._404}
)
def get_user_usage(
    dbuser: UserResponse = Depends(get_validated_user),
    start: str = "",
    end: str = "",
    db: Session = Depends(get_db),
):
    """Get users usage"""
    start, end = validate_dates(start, end)

    usages = crud.get_user_usages(db, dbuser, start, end)

    return {"usages": usages, "username": dbuser.username}


@router.post(
    "/user/{username}/active-next", response_model=UserResponse, responses={403: responses._403, 404: responses._404}
)
def active_next_plan(
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    dbuser: UserResponse = Depends(get_validated_user),
):
    """Reset user by next plan"""
    dbuser = crud.reset_user_by_next(db=db, dbuser=dbuser)

    if dbuser is None or dbuser.next_plan is None:
        raise HTTPException(
            status_code=404,
            detail="User doesn't have next plan",
        )

    if dbuser.status in [UserStatus.active, UserStatus.on_hold]:
        bg.add_task(xray.operations.add_user, dbuser=dbuser)

    user = UserResponse.model_validate(dbuser)
    bg.add_task(
        report.user_data_reset_by_next,
        user=user,
        user_admin=dbuser.admin,
    )

    logger.info(f'User "{dbuser.username}"\'s usage was reset by next plan')
    return dbuser


@router.get("/users/usage", response_model=UsersUsagesResponse)
def get_users_usage(
    start: str = "",
    end: str = "",
    db: Session = Depends(get_db),
    owner: list[str] | None = Query(None, alias="admin"),
    admin: Admin = Depends(Admin.get_current),
):
    """Get all users usage"""
    start, end = validate_dates(start, end)

    usages = crud.get_all_users_usages(db=db, start=start, end=end, admin=owner if admin.is_sudo else [admin.username])

    return {"usages": usages}


@router.post("/user/{username}/bs-extra", response_model=UserResponse)
def modify_user_bs_extra(
    payload: UserBsExtraModify,
    dbuser: UserResponse = Depends(get_validated_user),
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.get_current),
):
    """Инкремент или сброс остатка купленного БС-пула (bs_extra) пользователя."""
    del admin
    if not payload.reset and payload.delta_bytes is None:
        raise HTTPException(status_code=400, detail="Укажите delta_bytes или reset=true")
    if payload.reset and payload.delta_bytes is not None:
        raise HTTPException(status_code=400, detail="Нельзя указывать delta_bytes вместе с reset=true")
    try:
        updated_user = crud.modify_user_bs_extra(
            db,
            cast(DBUser, dbuser),
            delta_bytes=payload.delta_bytes,
            reset=payload.reset,
        )
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    user = UserResponse.model_validate(updated_user)
    logger.info(
        'User "%s" bs_extra updated: reset=%s delta=%s new_value=%s',
        user.username,
        payload.reset,
        payload.delta_bytes,
        user.bs_extra,
    )
    return user


@router.get("/user/{username}/bs-traffic", response_model=UserBsTrafficResponse)
def get_user_bs_traffic(
    dbuser: UserResponse = Depends(get_validated_user),
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.get_current),
):
    """Сводка БС-трафика пользователя: used/limit + купленный extra-пул."""
    del admin
    return crud.get_user_bs_traffic(db, cast(DBUser, dbuser))


@router.put("/user/{username}/set-owner", response_model=UserResponse)
def set_owner(
    admin_username: str,
    dbuser: UserResponse = Depends(get_validated_user),
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.check_sudo_admin),
):
    """Set a new owner (admin) for a user."""
    new_admin = crud.get_admin(db, username=admin_username)
    if not new_admin:
        raise HTTPException(status_code=404, detail="Admin not found")

    updated_user = crud.set_owner(db, dbuser, new_admin)
    user = UserResponse.model_validate(updated_user)

    logger.info(f'{user.username}"owner successfully set to{admin.username}')

    return user


@router.get("/users/expired", response_model=list[str])
def get_expired_users(
    expired_after: datetime | None = Query(None, example="2024-01-01T00:00:00"),
    expired_before: datetime | None = Query(None, example="2024-01-31T23:59:59"),
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.get_current),
):
    """
    Get users who have expired within the specified date range.

    - **expired_after** UTC datetime (optional)
    - **expired_before** UTC datetime (optional)
    - At least one of expired_after or expired_before must be provided for filtering
    - If both are omitted, returns all expired users
    """

    expired_after, expired_before = validate_dates(expired_after, expired_before)

    expired_users = get_expired_users_list(db, admin, expired_after, expired_before)
    return [u.username for u in expired_users]


@router.delete("/users/expired", response_model=list[str])
def delete_expired_users(
    bg: BackgroundTasks,
    expired_after: datetime | None = Query(None, example="2024-01-01T00:00:00"),
    expired_before: datetime | None = Query(None, example="2024-01-31T23:59:59"),
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.get_current),
):
    """
    Delete users who have expired within the specified date range.

    - **expired_after** UTC datetime (optional)
    - **expired_before** UTC datetime (optional)
    - At least one of expired_after or expired_before must be provided
    """
    expired_after, expired_before = validate_dates(expired_after, expired_before)

    expired_users = get_expired_users_list(db, admin, expired_after, expired_before)
    removed_users = [u.username for u in expired_users]

    if not removed_users:
        raise HTTPException(status_code=404, detail="No expired users found in the specified date range")

    crud.remove_users(db, expired_users)

    for removed_user in removed_users:
        logger.info(f'User "{removed_user}" deleted')
        bg.add_task(
            report.user_deleted,
            username=removed_user,
            user_admin=next((u.admin for u in expired_users if u.username == removed_user), None),
            by=admin,
        )

    return removed_users
