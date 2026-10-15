"""Кнопка «Помощь» на страницах подписки (NPVPN-2224)."""

from __future__ import annotations

import json
import pathlib
import re

import jinja2
import pytest

from app.subscription.support import build_support_context

_ROOT = pathlib.Path(__file__).parent.parent
CHAT = {
    "chat_base_url": "https://chat.example.com",
    "chat_website_token": "wt",
    "chat_identity_url": "https://api.example.com/web-api/v1/support/subscription-chat-identity",
}
TG = {"sub_support_url": "https://t.me/MyBot?start=support"}


def _render(template: str, support: dict) -> str:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(_ROOT / "app" / "templates" / "subscription")),
        undefined=jinja2.ChainableUndefined,
    )
    ctx = {
        "pay_url": "",
        "token": "TOKEN",
        "devices_json": "[]",
        "client_apps": {},
        "user": {},
        "devices": [],
        "sub_path": "sub",
        "web_url": "",
        "bot_url": "",
        "show_ads": True,
        "sub_statics": "/statics/subscription/",
        "support": support,
    }
    return env.get_template(template).render(ctx)


def _config(html: str) -> dict:
    match = re.search(r'<script type="application/json" data-support-config>(.*?)</script>', html, re.S)
    assert match, "нет конфига меню поддержки"
    return json.loads(match.group(1))


@pytest.mark.parametrize("template", ["index.html", "expired.html", "limited.html"])
def test_menu_with_chat_and_telegram(template):
    html = _render(template, build_support_context({**CHAT, **TG}, 7, "TOKEN"))
    assert "data-support-menu" in html
    assert "Чат на сайте" in html
    assert "Написать в Telegram" in html
    assert 'src="/statics/subscription/scripts/support-menu.js"' in html
    cfg = _config(html)
    assert cfg["chat"]["bot_id"] == 7
    assert cfg["token"] == "TOKEN"


def test_revoked_page_offers_only_telegram():
    html = _render("revoked.html", build_support_context({**CHAT, **TG}, 7, "TOKEN", allow_chat=False))
    assert "Связаться в Telegram" in html
    assert "Чат на сайте" not in html


def test_no_support_renders_nothing():
    html = _render("index.html", build_support_context({}, 7, "TOKEN"))
    assert "data-support-menu" not in html
    assert "support-menu.js" not in html


def test_config_json_cannot_break_out_of_script():
    """Review Focus 4: autoescape выключен — `</script>` в значении не должен закрыть тег."""
    support = build_support_context({**CHAT, "chat_website_token": "</script><script>alert(1)</script>"}, 7, "T")
    html = _render("index.html", support)
    assert "<script>alert(1)" not in html
    assert _config(html)["chat"]["website_token"] == "</script><script>alert(1)</script>"


def test_telegram_href_is_escaped():
    support = {"mode": "telegram", "tg_url": 'https://t.me/x"onclick="alert(1)', "chat": None, "token": "T"}
    html = _render("revoked.html", support)
    assert 'onclick="alert(1)' not in html


@pytest.mark.parametrize("template", ["index.html", "expired.html", "limited.html", "revoked.html"])
def test_include_once_right_before_body_end(template):
    html = _render(template, build_support_context({**CHAT, **TG}, 7, "TOKEN"))
    assert html.count("data-support-menu>") == 1
    assert re.search(r"support-menu\.js\"></script>\s*</body>", html)


def test_chat_mode_without_telegram_has_no_telegram_item():
    html = _render("index.html", build_support_context(CHAT, 7, "TOKEN"))
    assert "Написать в Telegram" not in html
    assert "Чат поддержки" in html
    assert "Чат на сайте" in html
    assert _config(html)["tg_url"] == ""
