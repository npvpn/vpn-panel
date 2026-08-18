from datetime import UTC, datetime
from typing import cast

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Path, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as SATimeoutError

from app import logger
from app.db import GetDB, Session, crud, get_db
from app.db.models import User
from app.dependencies import get_validated_sub, validate_dates
from app.models.user import SubscriptionUserResponse, UserResponse
from app.services.panel_settings import get_panel_settings
from app.subscription.bot_settings import resolve_bot_settings
from app.subscription.bs_context_builder import build_bs_context
from app.subscription.headers import build_content_disposition, get_routing_header
from app.subscription.not_found import render_not_found
from app.subscription.page import build_subscription_page_context
from app.subscription.share import generate_subscription
from app.subscription.subscription_service import (
    SubscriptionClientConfigEntry,
    SubscriptionRenderContext,
    SubscriptionRenderPlan,
    build_subscription_response_headers,
    resolve_announce_text,
    resolve_subscription_plan_by_client_type,
    resolve_subscription_plan_by_user_agent,
)
from app.subscription.user_info import (
    get_subscription_user_info,
    get_user_note,
    resolve_device_limit_subscription_state,
)
from app.templates import render_template
from app.utils.jwt import get_subscription_payload
from config import (
    SUBSCRIPTION_PAGE_TEMPLATE,
    USE_CUSTOM_JSON_DEFAULT,
    USE_CUSTOM_JSON_FOR_HAPP,
    USE_CUSTOM_JSON_FOR_STREISAND,
    USE_CUSTOM_JSON_FOR_V2RAYN,
    USE_CUSTOM_JSON_FOR_V2RAYNG,
    XRAY_SUBSCRIPTION_PATH,
)

client_config: dict[str, SubscriptionClientConfigEntry] = {
    "clash-meta": {"config_format": "clash-meta", "media_type": "text/yaml", "as_base64": False, "reverse": False},
    "sing-box": {"config_format": "sing-box", "media_type": "application/json", "as_base64": False, "reverse": False},
    "clash": {"config_format": "clash", "media_type": "text/yaml", "as_base64": False, "reverse": False},
    "v2ray": {"config_format": "v2ray", "media_type": "text/plain", "as_base64": True, "reverse": False},
    "outline": {"config_format": "outline", "media_type": "application/json", "as_base64": False, "reverse": False},
    "v2ray-json": {
        "config_format": "v2ray-json",
        "media_type": "application/json",
        "as_base64": False,
        "reverse": False,
    },
    "incy": {"config_format": "incy", "media_type": "text/plain", "as_base64": False, "reverse": False},
}

router = APIRouter(tags=["Subscription"], prefix=f"/{XRAY_SUBSCRIPTION_PATH}")


def resolve_subscription_context(token: str, db: Session):
    """
    Returns tuple: (dbuser or None, is_revoked: bool, created_at)
    - dbuser is None when token invalid/not found
    - is_revoked True when token is valid but revoked
    """
    sub = get_subscription_payload(token)
    if not sub:
        return None, False, None
    dbuser: User | None = crud.get_user(db, sub["username"])
    if not dbuser:
        return None, False, None
    # If token created before user record (e.g., renamed/recreated), treat as invalid
    if dbuser.created_at and sub.get("created_at") and dbuser.created_at > sub["created_at"]:
        return None, False, None
    revoked = bool(dbuser.sub_revoked_at and sub.get("created_at") and dbuser.sub_revoked_at > sub["created_at"])
    return dbuser, revoked, sub.get("created_at")


def _update_user_sub_bg(user_id: int, user_agent: str) -> None:
    """
    Фоновый апдейт users.sub_updated_at / sub_last_user_agent.
    Запускается через FastAPI BackgroundTasks ПОСЛЕ ответа клиенту, чтобы
    одиночный UPDATE по строке users не блокировал горячий путь /sub/ и
    не приводил к 500 (1205 Lock wait timeout exceeded), когда параллельно
    с /sub/ идут массовые UPDATE'ы users из mailing_queue / record_usages /
    edit_user. Поля sub_updated_at и sub_last_user_agent читаются только
    админкой панели (telegram/utils/shared.py) для информации, никакая
    бизнес-логика на их актуальности не строится, поэтому потеря одного
    апдейта (или задержка ~ms) безопасна.
    """
    try:
        with GetDB() as db:
            dbuser = db.query(User).filter(User.id == user_id).first()
            if dbuser is None:
                return
            crud.update_user_sub(db, dbuser, user_agent)
    except (SATimeoutError, OperationalError) as exc:
        # Lock wait / pool timeout — поле обновит следующий /sub-запрос.
        logger.warning(
            "[sub.update_bg] skip user_id=%s due to %s: %s",
            user_id,
            type(exc).__name__,
            exc,
        )
    except Exception as exc:
        logger.warning(
            "[sub.update_bg] unexpected error user_id=%s: %s: %s",
            user_id,
            type(exc).__name__,
            exc,
        )


def build_render_context(
    request: Request,
    db: Session,
    dbuser: User,
    user: UserResponse,
    bot_settings: dict,
    panel_settings: dict,
    *,
    is_revoked: bool,
    is_expired: bool,
    user_agent: str,
    x_hwid: str | None,
    x_device_os: str | None,
    x_ver_os: str | None,
    x_device_model: str | None,
) -> SubscriptionRenderContext:
    """Общий контекст обоих /sub-эндпоинтов: лимиты устройств, БС-контекст, заголовки."""
    user, device_limited, device_limited_hard, unsupported_blocks = resolve_device_limit_subscription_state(
        user,
        db,
        dbuser,
        is_revoked,
        is_expired,
        bot_settings,
        user_agent=user_agent,
        x_hwid=x_hwid,
        x_device_os=x_device_os,
        x_ver_os=x_ver_os,
        x_device_model=x_device_model,
    )
    # Хосты заблокированной БС-ноды (матч по связям host→nodes) остаются в подписке на
    # своих местах, но рендерятся как мёртвые заглушки (см. generate_subscription).
    bs = build_bs_context(db, dbuser, is_revoked=is_revoked, is_expired=is_expired, bot_settings=bot_settings)
    announce_text = resolve_announce_text(
        user,
        is_revoked=is_revoked,
        is_expired=is_expired,
        device_limited=device_limited,
        unsupported_blocks=unsupported_blocks,
        bs=bs,
        bot_settings=bot_settings,
        get_user_note=get_user_note,
    )
    user_info = get_subscription_user_info(user, db=db, panel_settings=panel_settings, user_id=cast(int, dbuser.id))
    subscription_userinfo = "; ".join(f"{key}={val}" for key, val in user_info.items())
    response_headers = build_subscription_response_headers(
        request=request,
        user=user,
        bot_settings=bot_settings,
        panel_settings=panel_settings,
        announce_text=announce_text,
        subscription_userinfo=subscription_userinfo,
        user_agent=user_agent,
        build_content_disposition=build_content_disposition,
        get_routing_header=get_routing_header,
    )
    return SubscriptionRenderContext(
        user=user,
        is_revoked=is_revoked,
        is_expired=is_expired,
        device_limited=device_limited,
        device_limited_hard=device_limited_hard,
        unsupported_blocks=unsupported_blocks,
        bot_settings=bot_settings,
        panel_settings=panel_settings,
        bs=bs,
        response_headers=response_headers,
    )


def render_subscription(ctx: SubscriptionRenderContext, plan: SubscriptionRenderPlan) -> Response:
    """Единая точка генерации ответа подписки по контексту и плану рендера."""
    conf = generate_subscription(
        user=ctx.user,
        config_format=plan.config_format,
        as_base64=plan.as_base64,
        reverse=plan.reverse,
        revoked=ctx.is_revoked,
        expired=ctx.is_expired,
        device_limited=ctx.device_limited,
        device_limited_hard=ctx.device_limited_hard,
        unsupported_client=ctx.unsupported_blocks,
        settings=ctx.bot_settings,
        panel_settings=ctx.panel_settings,
        bs=ctx.bs,
    )
    return Response(content=conf, media_type=plan.media_type, headers=ctx.response_headers)


@router.get("/{token}/")
@router.get("/{token}", include_in_schema=False)
def user_subscription(
    request: Request,
    token: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user_agent: str = Header(default=""),
    x_hwid: str | None = Header(default=None),
    x_device_os: str | None = Header(default=None),
    x_ver_os: str | None = Header(default=None),
    x_device_model: str | None = Header(default=None),
):
    """Provides a subscription link based on the user agent (Clash, V2Ray, etc.)."""
    # 1) Валидация токена и подготовка user/settings.
    dbuser, is_revoked, _ = resolve_subscription_context(token, db)
    if not dbuser:
        return render_not_found(request, db, token)
    crud.ensure_subscription_token(db, dbuser)
    is_expired = bool(dbuser.expire and dbuser.expire > 0 and dbuser.expire < int(datetime.now(UTC).timestamp()))
    user: UserResponse = UserResponse.model_validate(dbuser)
    bot_settings = resolve_bot_settings(dbuser)
    panel_settings = get_panel_settings(db)

    is_limited = not is_revoked and not is_expired and crud.is_device_limit_reached(db, dbuser)

    accept_header = request.headers.get("Accept", "")
    if "text/html" in accept_header:
        # HTML-ветка (страница подписки) обрабатывается отдельно от генерации конфигов.
        html_context = build_subscription_page_context(db, dbuser, token)
        if is_revoked:
            return HTMLResponse(render_template("sub/revoked.html", html_context))
        if is_expired:
            return HTMLResponse(render_template("sub/expired.html", html_context))
        if is_limited:
            return HTMLResponse(render_template("sub/limited.html", html_context))
        return HTMLResponse(render_template(SUBSCRIPTION_PAGE_TEMPLATE, html_context))

    # 2) Общий контекст рендера (лимиты устройств, БС-контекст, заголовки).
    ctx = build_render_context(
        request,
        db,
        dbuser,
        user,
        bot_settings,
        panel_settings,
        is_revoked=is_revoked,
        is_expired=is_expired,
        user_agent=user_agent,
        x_hwid=x_hwid,
        x_device_os=x_device_os,
        x_ver_os=x_ver_os,
        x_device_model=x_device_model,
    )

    # 3) Фоновый апдейт sub_updated_at / sub_last_user_agent — только на этом эндпоинте.
    if not is_revoked and not is_expired:
        background_tasks.add_task(_update_user_sub_bg, dbuser.id, user_agent)

    # 4) Выбор плана рендера по User-Agent и возврат ответа.
    plan = resolve_subscription_plan_by_user_agent(
        user_agent,
        use_custom_json_default=USE_CUSTOM_JSON_DEFAULT,
        use_custom_json_for_v2rayn=USE_CUSTOM_JSON_FOR_V2RAYN,
        use_custom_json_for_v2rayng=USE_CUSTOM_JSON_FOR_V2RAYNG,
        use_custom_json_for_streisand=USE_CUSTOM_JSON_FOR_STREISAND,
        use_custom_json_for_happ=USE_CUSTOM_JSON_FOR_HAPP,
    )
    return render_subscription(ctx, plan)


@router.get("/{token}/devices/{device_id}/revoke", include_in_schema=False)
@router.post("/{token}/devices/{device_id}/revoke", include_in_schema=False)
def revoke_subscription_device(
    request: Request,
    token: str,
    device_id: int,
    db: Session = Depends(get_db),
):
    dbuser, is_revoked, _ = resolve_subscription_context(token, db)
    if not dbuser:
        return render_not_found(request, db, token)

    is_expired = bool(dbuser.expire and dbuser.expire > 0 and dbuser.expire < int(datetime.now(UTC).timestamp()))
    if is_revoked or is_expired:
        raise HTTPException(status_code=403, detail="Subscription is not active")

    dbdevice = crud.get_user_device(db, dbuser, device_id)
    if not dbdevice or dbdevice.status != "active":
        raise HTTPException(status_code=404, detail="Active device not found")

    crud.revoke_user_device(db, dbdevice)
    if request.method == "POST":
        return Response(status_code=204)
    return RedirectResponse(url=f"/{XRAY_SUBSCRIPTION_PATH}/{token}", status_code=303)


@router.get("/{token}/info", response_model=SubscriptionUserResponse)
def user_subscription_info(
    dbuser: UserResponse = Depends(get_validated_sub),
):
    """Retrieves detailed information about the user's subscription."""
    return dbuser


@router.get("/{token}/usage")
def user_get_usage(
    dbuser: UserResponse = Depends(get_validated_sub), start: str = "", end: str = "", db: Session = Depends(get_db)
):
    """Fetches the usage statistics for the user within a specified date range."""
    start, end = validate_dates(start, end)

    usages = crud.get_user_usages(db, dbuser, start, end)

    return {"usages": usages, "username": dbuser.username}


@router.get("/{token}/{client_type}")
def user_subscription_with_client_type(
    request: Request,
    token: str,
    client_type: str = Path(..., regex="sing-box|clash-meta|clash|outline|v2ray|v2ray-json|incy"),
    db: Session = Depends(get_db),
    user_agent: str = Header(default=""),
    x_hwid: str | None = Header(default=None),
    x_device_os: str | None = Header(default=None),
    x_ver_os: str | None = Header(default=None),
    x_device_model: str | None = Header(default=None),
):
    """Provides a subscription link based on the specified client type (e.g., Clash, V2Ray)."""
    # Эндпоинт с явным client_type: схема похожа на /{token}, но план
    # рендера выбирается не по UA, а по параметру пути.
    dbuser, is_revoked, _ = resolve_subscription_context(token, db)
    if not dbuser:
        return render_not_found(request, db, token)
    crud.ensure_subscription_token(db, dbuser)
    is_expired = bool(dbuser.expire and dbuser.expire > 0 and dbuser.expire < int(datetime.now(UTC).timestamp()))
    user: UserResponse = UserResponse.model_validate(dbuser)
    bot_settings = resolve_bot_settings(dbuser)
    panel_settings = get_panel_settings(db)

    ctx = build_render_context(
        request,
        db,
        dbuser,
        user,
        bot_settings,
        panel_settings,
        is_revoked=is_revoked,
        is_expired=is_expired,
        user_agent=user_agent,
        x_hwid=x_hwid,
        x_device_os=x_device_os,
        x_ver_os=x_ver_os,
        x_device_model=x_device_model,
    )

    try:
        # Централизованный выбор формата/типов ответа по client_type.
        plan = resolve_subscription_plan_by_client_type(
            client_type,
            client_config=client_config,
            use_custom_json_default=USE_CUSTOM_JSON_DEFAULT,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Unknown client type") from exc
    return render_subscription(ctx, plan)
