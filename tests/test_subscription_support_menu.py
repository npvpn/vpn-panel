"""Поддержка на страницах подписки (NPVPN-2224, NPVPN-2314)."""

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


HEADER_TOP = r'<div class="page-header__top">(.*?)</div>\s*</div>'
TG_PATH, HEADER_CHAT_PATH = 'd="M10.3078', 'd="M21 11.9999'


def _floating(html: str) -> str:
    match = re.search(r'<div class="support-menu support-menu--floating"(.*?)</div>\s*<script defer', html, re.S)
    assert match, "нет плавающей кнопки"
    return match.group(1)


@pytest.mark.parametrize("template", ["index.html", "expired.html", "limited.html"])
def test_menu_with_chat_and_telegram(template):
    html = _render(template, build_support_context({**CHAT, **TG}, 7, "TOKEN"))
    assert "data-support-menu" in html
    assert "Написать в чат" in html
    assert ">Telegram<" in html
    assert 'src="/statics/subscription/scripts/support-menu.js"' in html
    cfg = _config(html)
    assert cfg["chat"]["bot_id"] == 7
    assert cfg["token"] == "TOKEN"


def test_revoked_page_offers_only_telegram():
    html = _render("revoked.html", build_support_context({**CHAT, **TG}, 7, "TOKEN", allow_chat=False))
    assert ">Telegram<" in html
    assert "Написать в чат" not in html
    assert "data-support-toggle" not in html


def test_no_support_renders_nothing():
    html = _render("index.html", build_support_context({}, 7, "TOKEN"))
    assert "data-support-menu" not in html
    assert "support-menu.js" not in html
    assert "support-menu.css" not in html


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
def test_floating_button_once_with_script_right_before_body_end(template):
    html = _render(template, build_support_context({**CHAT, **TG}, 7, "TOKEN"))
    assert html.count("support-menu--floating") == 1
    assert html.count("support-menu.js") == 1
    assert re.search(r"support-menu\.js\"></script>\s*</body>", html)


@pytest.mark.parametrize("template", ["index.html", "expired.html", "limited.html", "revoked.html"])
def test_header_has_support_icon(template):
    # Мобилка: значок поддержки в шапке (на index.html — рядом с «Личным кабинетом»).
    html = _render(template, build_support_context({**CHAT, **TG}, 7, "TOKEN"))
    headers = re.findall(HEADER_TOP, html, re.S)
    assert headers and all("support-menu--header" in h for h in headers)


def test_index_has_no_support_in_bottom_nav_or_sidebar():
    # NPVPN-2314: «Помощь» из нижнего меню и пункт сайдбара убраны — их заменили шапка и плавающая кнопка.
    for ctx in ({**CHAT, **TG}, TG):
        html = _render("index.html", build_support_context(ctx, 7, "TOKEN"))
        nav = re.search(r'<nav class="floating-nav">(.*?)</nav>', html, re.S)
        sidebar = re.search(r'<nav class="sidebar-nav">(.*?)</nav>', html, re.S)
        assert nav and "data-support-menu" not in nav.group(1)
        assert sidebar and "data-support-menu" not in sidebar.group(1)
        assert "Помощь" not in html


@pytest.mark.parametrize("template", ["index.html", "expired.html", "limited.html"])
def test_both_channels_header_opens_sheet(template):
    html = _render(template, build_support_context({**CHAT, **TG}, 7, "TOKEN"))
    header = re.search(HEADER_TOP, html, re.S).group(1)
    assert HEADER_CHAT_PATH in header and "data-support-toggle" in header
    assert "support-menu__list--sheet" in header
    assert "Как хотите связаться" in header and "data-support-close" in header
    assert "Написать в чат" in header and TG["sub_support_url"] in header
    # на index.html шапок три — у шторки нет id, иначе они бы повторялись
    assert 'id="support-sheet' not in html


@pytest.mark.parametrize("template", ["index.html", "expired.html", "limited.html", "revoked.html"])
def test_telegram_only_header_icon_is_link(template):
    html = _render(template, build_support_context(TG, 7, "TOKEN"))
    header = re.search(HEADER_TOP, html, re.S).group(1)
    assert 'aria-label="Telegram"' in header and TG["sub_support_url"] in header
    assert TG_PATH in header and "data-support-toggle" not in header


@pytest.mark.parametrize("template", ["index.html", "expired.html", "limited.html"])
def test_chat_only_header_icon_opens_chat_without_sheet(template):
    html = _render(template, build_support_context(CHAT, 7, "TOKEN"))
    header = re.search(HEADER_TOP, html, re.S).group(1)
    assert HEADER_CHAT_PATH in header and "data-support-toggle" in header
    assert "support-menu__list--sheet" not in header
    assert "data-support-status" in header


def test_floating_both_channels_is_chat_with_close_swap():
    floating = _floating(_render("index.html", build_support_context({**CHAT, **TG}, 7, "TOKEN")))
    assert ">Чат<" in floating
    assert "support-menu__swap" in floating and "support-menu__icon--close" in floating
    assert "Написать в чат" in floating and ">Telegram<" in floating


def test_floating_telegram_only_is_link():
    floating = _floating(_render("index.html", build_support_context(TG, 7, "TOKEN")))
    assert ">Telegram<" in floating and TG["sub_support_url"] in floating
    assert "data-support-toggle" not in floating


def test_chat_mode_without_telegram_has_no_fork():
    # Один вариант — без вилки: кнопка сразу открывает чат, пунктов меню нет.
    html = _render("index.html", build_support_context(CHAT, 7, "TOKEN"))
    assert "Telegram" not in html
    assert "Написать в чат" not in html
    assert "data-support-chat" not in html
    assert ">Чат<" in _floating(html)
    cfg = _config(html)
    assert cfg["mode"] == "chat"
    assert cfg["tg_url"] == ""
