"""Вход в поддержку со страницы подписки и из VPN-приложения (NPVPN-2224).

Онлайн-чат — Chatwoot Website inbox бота; identity подписывает бот по токену
подписки (`chat_identity_url`), секрет в панель не попадает. Telegram-ссылка —
прежний `sub_support_url`. Значения приходят из синка настроек бота, а
autoescape в jinja-Environment панели выключен — в href и src пускаем только
http(s) (та же причина, что у `resolve_pay_url`, NPVPN-1762/1848).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

from config import XRAY_SUBSCRIPTION_PATH

SUPPORT_OPEN_PARAM = "support"
SUPPORT_OPEN_VALUE = "open"
_HTTP_SCHEMES = ("http://", "https://")
_UNSAFE_URL_CHARS = frozenset("\"'<> \t\r\n`")


def _http_url(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not text.lower().startswith(_HTTP_SCHEMES) or any(ch in _UNSAFE_URL_CHARS for ch in text):
        return ""
    return text


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _chat_configured(bot_settings: dict) -> bool:
    return bool(
        _http_url(bot_settings.get("chat_base_url"))
        and _http_url(bot_settings.get("chat_identity_url"))
        and _text(bot_settings.get("chat_website_token"))
    )


def resolve_support_chat(bot_settings: dict, source_bot_id: int | None) -> dict | None:
    if not source_bot_id or not _chat_configured(bot_settings):
        return None
    return {
        "base_url": _http_url(bot_settings.get("chat_base_url")).rstrip("/"),
        "website_token": _text(bot_settings.get("chat_website_token")),
        "identity_url": _http_url(bot_settings.get("chat_identity_url")),
        "bot_id": int(source_bot_id),
    }


def build_support_context(
    bot_settings: dict, source_bot_id: int | None, token: str, *, allow_chat: bool = True
) -> dict:
    tg_url = _http_url(bot_settings.get("sub_support_url"))
    chat = resolve_support_chat(bot_settings, source_bot_id) if allow_chat else None
    if chat and tg_url:
        mode = "menu"
    elif chat:
        mode = "chat"
    elif tg_url:
        mode = "telegram"
    else:
        mode = "none"
    return {"mode": mode, "tg_url": tg_url, "chat": chat, "token": token}


def resolve_support_url_header(bot_settings: dict, request_url: str, token: str, *, revoked: bool = False) -> str:
    """`support-url` для VPN-приложений.

    Чат настроен и токен жив -> страница подписки этого же юзера с автооткрытием
    «Помощи». Путь строим от `XRAY_SUBSCRIPTION_PATH` и токена, а не от пути
    запроса: заголовок отдают и `/sub/TOKEN/<client_type>`, где HTML-ветки нет.
    Из запроса берём только хост. Схема принудительно https: панель за прокси
    видит запрос как http, а приложение пришло по публичной https-ссылке.
    У отозванного токена identity не получить (как и на странице) — Telegram.
    """
    if revoked or not _chat_configured(bot_settings):
        return str(bot_settings.get("sub_support_url") or "")
    netloc = urlsplit(request_url).netloc
    path = f"/{XRAY_SUBSCRIPTION_PATH}/{quote(token, safe='')}"
    return urlunsplit(("https", netloc, path, urlencode({SUPPORT_OPEN_PARAM: SUPPORT_OPEN_VALUE}), ""))
