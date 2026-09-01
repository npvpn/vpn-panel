import json
import math
from datetime import UTC, datetime

from app.db import Session, crud
from app.db.models import User
from app.models.user import UserResponse


def devices_json(devices) -> str:
    return json.dumps(
        [
            {
                "id": device.id,
                "device_model": device.device_model or "Неизвестная модель",
                "device_os": device.device_os or "Неизвестно",
                "ver_os": device.ver_os or "",
                "user_agent": device.user_agent or "",
            }
            for device in devices
        ],
        ensure_ascii=False,
    )


def get_user_note(user: UserResponse, note_template: str) -> str:
    """Return note from SUB_CLIENT_NOTE with <days_left> and <tg_id> placeholders."""
    if not note_template:
        return ""
    note_template = note_template.replace("<tg_id>", user.username.split("_", 1)[0])
    expire_ts = int(user.expire or 0)
    if expire_ts <= 0:
        return note_template.replace("<days_left>", "0")
    now_ts = int(datetime.now(UTC).timestamp())
    seconds_left = max(0, expire_ts - now_ts)
    days_left = math.ceil(seconds_left / 86400)
    return note_template.replace("<days_left>", str(days_left))


def get_subscription_user_info(user: UserResponse, *, db=None, panel_settings=None, user_id: int | None = None) -> dict:
    """upload/download/total/expire для Happ. Если задан общий БС-лимит панели и есть
    БС-расход — download/total отражают месячный агрегат БС, иначе глобальный."""
    info = {
        "upload": 0,
        "download": user.used_traffic,
        "total": user.data_limit if user.data_limit is not None else 0,
        "expire": user.expire if user.expire is not None else 0,
    }
    if db is None or panel_settings is None or user_id is None:
        return info

    monthly_limit = panel_settings.get("bs_monthly_limit") or 0
    if not monthly_limit:
        return info

    from app.xray.bs_limit import monthly_effective_limit, period_keys, pick_bs_bar

    yyyymm = period_keys(datetime.utcnow())
    pool = crud.normalize_bs_extra_period(db, user_id, monthly_limit, yyyymm, persist=False)
    monthly_limit_eff = monthly_effective_limit(monthly_limit, pool)
    monthly_used = crud.get_bs_usage_totals(db, user_id, yyyymm)
    bar = pick_bs_bar(monthly_used, monthly_limit_eff)
    if bar is not None:
        info["download"], info["total"] = bar
    return info


def get_empty_subscription_user(user: UserResponse) -> UserResponse:
    return user.model_copy(update={"proxies": {}, "inbounds": {}})


def resolve_device_limit_subscription_state(
    user: UserResponse,
    db: Session,
    dbuser: User,
    is_revoked: bool,
    is_expired: bool,
    bot_settings: dict,
    *,
    user_agent: str,
    x_hwid: str | None,
    x_device_os: str | None,
    x_ver_os: str | None,
    x_device_model: str | None,
) -> tuple[UserResponse, bool, bool, bool]:
    """Returns user, device_limited, device_limited_hard_for_gen, unsupported_blocks."""
    device_limited = False
    device_limited_hard_for_gen = False
    unsupported_client = False
    hard_mode = bool(bot_settings.get("sub_device_limit_hard_mode"))
    if not is_revoked and not is_expired:
        registered, unsupported_client = crud.register_user_device(
            db,
            dbuser,
            x_hwid,
            x_device_os,
            x_ver_os,
            x_device_model,
            user_agent,
            hard_mode=hard_mode,
        )
        dbdevice = None
        if registered:
            dbdevice = crud.get_user_device_by_hwid(db, dbuser, x_hwid or crud.UNKNOWN_DEVICE_HWID)
        within_limit = crud.is_device_within_limit(db, dbuser, dbdevice)
        over_limit = not unsupported_client and not within_limit
        device_limited = over_limit
        device_limited_hard_for_gen = over_limit and hard_mode
    unsupported_blocks = unsupported_client
    if is_revoked or is_expired or unsupported_blocks or device_limited_hard_for_gen:
        user = get_empty_subscription_user(user)
    return user, device_limited, device_limited_hard_for_gen, unsupported_blocks
