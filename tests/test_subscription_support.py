"""Поддержка на странице подписки и в заголовке support-url (NPVPN-2224)."""

from __future__ import annotations

import pytest

from app.subscription.support import build_support_context, resolve_support_chat, resolve_support_url_header

CHAT = {
    "chat_base_url": "https://chat.example.com",
    "chat_website_token": "wt",
    "chat_identity_url": "https://api.example.com/web-api/v1/support/subscription-chat-identity",
}
TG = {"sub_support_url": "https://t.me/MyBot?start=support"}
SUB_URL = "http://panel.example.com:8001/sub/TOKEN"


def test_header_points_to_subscription_page_when_chat_configured():
    assert (
        resolve_support_url_header({**CHAT, **TG}, SUB_URL, "TOKEN")
        == "https://panel.example.com:8001/sub/TOKEN?support=open"
    )


def test_header_ignores_client_type_suffix_and_request_query():
    """/sub/TOKEN/v2ray-json отдаёт конфиг, а не страницу — ссылка всегда на страницу подписки."""
    url = resolve_support_url_header({**CHAT, **TG}, "http://h:8001/sub/TOKEN/v2ray-json?x=1", "TOKEN")
    assert url == "https://h:8001/sub/TOKEN?support=open"


def test_header_quotes_token_as_one_path_segment():
    url = resolve_support_url_header({**CHAT, **TG}, SUB_URL, "a/b?c")
    assert url == "https://panel.example.com:8001/sub/a%2Fb%3Fc?support=open"


def test_header_falls_back_to_telegram_without_chat():
    """Review Focus 5."""
    assert resolve_support_url_header(TG, SUB_URL, "TOKEN") == TG["sub_support_url"]
    assert (
        resolve_support_url_header({**CHAT, "chat_identity_url": "", **TG}, SUB_URL, "TOKEN") == TG["sub_support_url"]
    )


def test_header_falls_back_to_telegram_when_revoked():
    assert resolve_support_url_header({**CHAT, **TG}, SUB_URL, "TOKEN", revoked=True) == TG["sub_support_url"]
    assert resolve_support_url_header(CHAT, SUB_URL, "TOKEN", revoked=True) == ""


def test_chat_requires_all_fields_http_urls_and_bot():
    assert resolve_support_chat(CHAT, 7) == {
        "base_url": "https://chat.example.com",
        "website_token": "wt",
        "identity_url": CHAT["chat_identity_url"],
        "bot_id": 7,
    }
    assert resolve_support_chat(CHAT, None) is None
    assert resolve_support_chat({**CHAT, "chat_base_url": "javascript:alert(1)"}, 7) is None
    assert resolve_support_chat({**CHAT, "chat_website_token": ""}, 7) is None


@pytest.mark.parametrize(
    ("settings", "allow_chat", "mode"),
    [
        ({**CHAT, **TG}, True, "menu"),
        (CHAT, True, "chat"),
        (TG, True, "telegram"),
        ({}, True, "none"),
        ({**CHAT, **TG}, False, "telegram"),  # revoked: токен отозван — identity не получить
        (CHAT, False, "none"),
    ],
)
def test_support_modes(settings, allow_chat, mode):
    ctx = build_support_context(settings, 7, "TOKEN", allow_chat=allow_chat)
    assert ctx["mode"] == mode
    assert ctx["token"] == "TOKEN"
    assert (ctx["chat"] is not None) == (mode in ("menu", "chat"))


@pytest.mark.parametrize("raw", ["javascript:alert(1)", '" onmouseover="x', "//evil.com", None, 123])
def test_non_http_tg_url_is_dropped(raw):
    """Review Focus 4: autoescape выключен — в href попадает только http(s)."""
    assert build_support_context({"sub_support_url": raw}, 7, "T")["tg_url"] == ""


def test_new_fields_are_managed_and_accepted():
    """extra='forbid': без полей в модели push бота роняет синк всех ботов (см. NPVPN-1848)."""
    from app.models.managed import ManagedBotSettingsPayload
    from app.services.managed_settings import BOT_MANAGED_JSON_FIELDS

    payload = ManagedBotSettingsPayload.model_validate(
        {
            "username": "synced_bot",
            "bot_url": "https://t.me/synced_bot",
            "web_url": "",
            "sub_support_url": "https://t.me/support",
            "sub_subscription_domain": "",
            **CHAT,
        }
    )
    assert payload.chat_website_token == "wt"
    assert set(CHAT) <= BOT_MANAGED_JSON_FIELDS


def test_defaults_have_empty_chat_fields():
    from app.models.bot import DEFAULT_BOT_SETTINGS, BotSettingsPayload

    for key in CHAT:
        assert DEFAULT_BOT_SETTINGS[key] == ""
        assert getattr(BotSettingsPayload(), key) == ""


def _response_headers(bot_settings: dict, *, revoked: bool = False) -> dict:
    from types import SimpleNamespace

    from app.subscription.subscription_service import build_subscription_response_headers

    return build_subscription_response_headers(
        request=SimpleNamespace(url="http://h:8001/sub/TOKEN/v2ray-json?x=1"),
        user=SimpleNamespace(username="u1"),
        bot_settings={
            "sub_profile_url": "",
            "sub_profile_title": "t",
            "bot_url": "",
            "sub_update_interval": 12,
            "sub_support_url": "",
            **bot_settings,
        },
        panel_settings={},
        announce_text="",
        subscription_userinfo="",
        user_agent="",
        token="TOKEN",
        is_revoked=revoked,
        build_content_disposition=lambda name: name,
        get_routing_header=lambda *_a: {},
    )


def test_response_headers_wiring_support_url():
    assert _response_headers({**CHAT, **TG})["support-url"] == "https://h:8001/sub/TOKEN?support=open"
    assert _response_headers(TG)["support-url"] == TG["sub_support_url"]
    assert _response_headers({**CHAT, **TG}, revoked=True)["support-url"] == TG["sub_support_url"]


def test_announce_url_prefers_web_url():
    assert _response_headers({"web_url": "https://cab.example", "bot_url": "https://t.me/bot"})["announce-url"] == (
        "https://cab.example"
    )
    assert _response_headers({"web_url": "  ", "bot_url": "https://t.me/bot"})["announce-url"] == "https://t.me/bot"
    assert _response_headers({"bot_url": "https://t.me/bot"})["announce-url"] == "https://t.me/bot"


@pytest.mark.parametrize(("revoked", "mode", "has_chat"), [(False, "menu", True), (True, "telegram", False)])
def test_page_context_passes_source_bot_id_and_revoked(monkeypatch, revoked, mode, has_chat):
    import sys
    import types
    from types import SimpleNamespace

    # share.py в этом окружении не импортируется в одиночку (цикл app.db -> models.user -> share);
    # как и соседние тесты, подменяем его заглушкой — для контекста страницы он не нужен.
    share_stub = types.ModuleType("app.subscription.share")
    share_stub.generate_v2ray_links = lambda *_a, **_k: []
    monkeypatch.setitem(sys.modules, "app.subscription.share", share_stub)
    from app.subscription import page

    monkeypatch.setattr(page, "resolve_bot_settings", lambda _dbuser: {"bot_url": "", **CHAT, **TG})
    monkeypatch.setattr(page.crud, "get_user_active_devices", lambda *_a: [])
    monkeypatch.setattr(page.crud, "get_global_setting", lambda *_a: None)
    monkeypatch.setattr(page, "devices_json", lambda _d: "[]")
    monkeypatch.setattr(page.UserResponse, "model_validate", classmethod(lambda _cls, obj: obj))
    dbuser = SimpleNamespace(bot=SimpleNamespace(source_bot_id=7))

    ctx = page.build_subscription_page_context(None, dbuser, "TOKEN", revoked=revoked)

    assert ctx["support"]["mode"] == mode
    assert ctx["support"]["token"] == "TOKEN"
    assert (ctx["support"]["chat"] is not None) == has_chat
    if has_chat:
        assert ctx["support"]["chat"]["bot_id"] == 7
