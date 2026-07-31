"""404-страница подписки: резолв ссылки для кнопки «На главную» (NPVPN-1762).

404 отдаётся ровно тогда, когда пользователь не найден, а bot_url/web_url в панели
живут пер-бот. Поэтому бота ищем в три ступени, от точного к грубому:

1. По токену: он разбирается (подпись валидна) даже когда пользователь уже пересоздан
   или переименован — тогда запись в базе есть и бот известен точно.
2. Одноботовая панель: пользователя нет, но и выбирать не из чего. Ноль ботов —
   классический одиночный Marzban, где ссылка живёт в env.
3. Мультиботовая панель: угадывать нечего, ссылки нет и кнопки не будет. Через
   apply_bot_settings_fallback(None) здесь идти НЕЛЬЗЯ — он подставит env BOT_URL,
   и пользователь уедет в чужого бота.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request, Response
from fastapi.responses import HTMLResponse

from app import logger
from app.db import Session, crud
from app.models.bot import apply_bot_settings_fallback
from app.subscription.bot_settings import resolve_bot_settings
from app.templates import render_template
from app.utils.jwt import get_subscription_payload

NOT_FOUND_TEMPLATE = "sub/not_found.html"


def render_not_found(request: Request, db: Session, token: str) -> Response:
    """404 подписки: браузеру — оформленная страница, VPN-клиентам и API — пустой ответ."""
    if "text/html" not in request.headers.get("Accept", ""):
        return Response(status_code=404)
    context = build_not_found_page_context(db, token)
    return HTMLResponse(render_template(NOT_FOUND_TEMPLATE, context), status_code=404)


def build_not_found_page_context(db: Session, token: str) -> dict[str, Any]:
    """Контекст jinja-шаблона 404: куда ведёт кнопка и показывать ли футер с рекламой."""
    settings = _resolve_settings_without_user(db, token)
    if settings is None:
        return {"home_url": "", "show_ads": True}
    home_url = (settings.get("web_url") or "").strip() or (settings.get("bot_url") or "").strip()
    return {"home_url": home_url, "show_ads": bool(settings.get("show_ads", True))}


def _resolve_settings_without_user(db: Session, token: str) -> dict[str, Any] | None:
    """Настройки бота, которого удалось определить, или None — если определять нечего."""
    try:
        payload = get_subscription_payload(token)
        if payload:
            dbuser = crud.get_user(db, payload["username"])
            if dbuser is not None:
                return resolve_bot_settings(dbuser)

        bots = crud.get_bots(db)
        if len(bots) <= 1:
            bot = bots[0] if bots else None
            raw = bot.settings.data if bot is not None and bot.settings else None
            return apply_bot_settings_fallback(raw)
    except Exception:
        # 404 обязана отдаваться всегда: сломанный резолв просто оставляет страницу без кнопки.
        logger.warning("[sub] не удалось определить бота для 404-страницы", exc_info=True)
    return None
