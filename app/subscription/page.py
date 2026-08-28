from __future__ import annotations

from app.db import Session, crud
from app.models.settings import CLIENT_APPS_KEY
from app.models.user import UserResponse
from app.subscription.bot_settings import resolve_bot_settings
from app.subscription.client_apps import build_client_apps_view
from app.subscription.user_info import devices_json
from config import XRAY_SUBSCRIPTION_PATH

_ALLOWED_PAY_URL_SCHEMES = ("http://", "https://")


def resolve_pay_url(bot_settings: dict) -> str:
    """Ссылка кнопки оплаты или пустая строка.

    Значение приходит из настроек бота, а шаблон подставляет его в href без
    экранирования (autoescape выключен на уровне общего jinja-Environment) —
    отсекаем всё, что не http(s)-ссылка. Та же причина, что и у home_url в
    app/subscription/not_found.py (NPVPN-1762).
    """
    value = str((bot_settings or {}).get("sub_pay_url") or "").strip()
    if not value.lower().startswith(_ALLOWED_PAY_URL_SCHEMES):
        return ""
    return value


def build_subscription_page_context(db: Session, dbuser, token: str) -> dict:
    """Контекст jinja-шаблона страницы подписки (HTML-ветка)."""
    bot_settings = resolve_bot_settings(dbuser)
    devices = crud.get_user_active_devices(db, dbuser)
    return {
        "user": UserResponse.model_validate(dbuser),
        "devices": devices,
        "devices_json": devices_json(devices),
        "token": token,
        "sub_path": XRAY_SUBSCRIPTION_PATH,
        "web_url": (bot_settings.get("web_url") or "").strip(),
        "bot_url": bot_settings["bot_url"],
        "show_ads": bool(bot_settings.get("show_ads", True)),
        "pay_url": resolve_pay_url(bot_settings),
        "client_apps": build_client_apps_view(crud.get_global_setting(db, CLIENT_APPS_KEY)),
    }
