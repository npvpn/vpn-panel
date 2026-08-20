"""Кнопка оплаты на странице подписки (NPVPN-1848).

Санитайз схемы обязателен: autoescape в jinja-Environment панели выключен,
шаблон подставляет ссылку в href как есть — ровно та же причина, по которой
он есть в not_found.py (NPVPN-1762).
"""

from __future__ import annotations

import pathlib

import pytest

from app.subscription.page import resolve_pay_url

_ROOT = pathlib.Path(__file__).parent.parent
_PAY_URL = "https://api.example.com/pay/resume/7"
_TOKEN = "eyJhbGciOiJIUzI1NiJ9.payload.signature"


def _page_context(*, pay_url: str, token: str, web_url: str = "") -> dict:
    """Минимум, без которого шаблон не рендерится (tojson не терпит Undefined)."""
    return {
        "pay_url": pay_url,
        "token": token,
        "devices_json": "[]",
        "client_apps": {},
        "user": {},
        "devices": [],
        "sub_path": "sub",
        "web_url": web_url,
        "bot_url": "",
        "show_ads": True,
    }


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://api.example.com/pay/resume/7", "https://api.example.com/pay/resume/7"),
        ("http://api.example.com/pay/resume/7", "http://api.example.com/pay/resume/7"),
        ("", ""),
        (None, ""),
        ("javascript:alert(1)", ""),
        ("  https://api.example.com/pay/resume/7  ", "https://api.example.com/pay/resume/7"),
    ],
)
def test_resolve_pay_url(raw, expected):
    assert resolve_pay_url({"sub_pay_url": raw}) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "JAVASCRIPT:ALERT(1)",
        "javascript:alert(1)",
        "  JavaScript:alert(1)  ",
        "data:text/html,<script>alert(1)</script>",
        "//evil.com",
        "/pay/resume/7",
        "evil.com/pay",
        123,
        ["https://api.example.com/pay/resume/7"],
        {"url": "https://api.example.com/pay/resume/7"},
        {},
        [],
        True,
    ],
)
def test_non_http_values_are_dropped(raw):
    """href подставляется без экранирования — всё, что не http(s)-строка, обязано схлопнуться в ''."""
    assert resolve_pay_url({"sub_pay_url": raw}) == ""


def test_missing_key_gives_empty_string():
    assert resolve_pay_url({}) == ""


def test_template_href_carries_base_url_and_token():
    """Токен знает только панель — базовый URL из настроек склеивается с токеном в шаблоне.

    Собственный Environment, а не app.templates: тот тянет config и БД-зависимости,
    а нас интересует ровно разметка кнопки.
    """
    import jinja2

    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(_ROOT / "app" / "templates")),
        undefined=jinja2.ChainableUndefined,
    )
    html = env.get_template("subscription/index.html").render(_page_context(pay_url=_PAY_URL, token=_TOKEN))

    assert f'href="{_PAY_URL}/{_TOKEN}"' in html


def test_template_hides_button_without_pay_url():
    import jinja2

    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(_ROOT / "app" / "templates")),
        undefined=jinja2.ChainableUndefined,
    )
    html = env.get_template("subscription/index.html").render(_page_context(pay_url="", token=_TOKEN))

    assert "Продлить подписку" not in html


def test_managed_payload_accepts_sub_pay_url():
    """extra='forbid': незнакомый ключ в payload'е роняет весь settings_sync, а не только эту фичу."""
    from app.models.managed import ManagedBotSettingsPayload

    payload = ManagedBotSettingsPayload.model_validate(
        {
            "username": "synced_bot",
            "title": "Synced bot",
            "bot_url": "https://t.me/synced_bot",
            "web_url": "https://cab.example.com",
            "sub_support_url": "https://t.me/support",
            "sub_subscription_domain": "sub.example.com",
            "sub_pay_url": _PAY_URL,
        }
    )

    assert payload.sub_pay_url == _PAY_URL


def test_sub_pay_url_is_a_managed_json_field():
    """Иначе значение не доедет до BotSettings.data и не будет защищено от затирания из панели."""
    from app.services.managed_settings import BOT_MANAGED_JSON_FIELDS

    assert "sub_pay_url" in BOT_MANAGED_JSON_FIELDS


def _render(template: str, **ctx) -> str:
    """Рендер настоящего шаблона обоими каталогами — как это делает app/templates/__init__.py."""
    import jinja2

    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader([str(_ROOT / "app" / "templates"), str(_ROOT / "templates")]),
        undefined=jinja2.ChainableUndefined,
    )
    return env.get_template(template).render(_page_context(**ctx))


def test_expired_page_shows_pay_button_without_web_cabinet():
    """Просроченным отдаётся sub/expired.html, а НЕ subscription/index.html.

    Кнопка, поставленная только в index.html, не показывалась вообще никому:
    активные не просрочены, а просроченные видят другой шаблон (NPVPN-1848).
    """
    html = _render("sub/expired.html", pay_url=_PAY_URL, token=_TOKEN, web_url="")

    assert f'href="{_PAY_URL}/{_TOKEN}"' in html
    assert "Продлить подписку" in html


def test_expired_page_prefers_cabinet_when_web_exists():
    """С веб-кабинетом путь к оплате уже есть — по DofD кнопка только «для челов без веба»."""
    html = _render("sub/expired.html", pay_url=_PAY_URL, token=_TOKEN, web_url="https://cab.example.com")

    assert "Войти в личный кабинет" in html
    assert _PAY_URL not in html


def test_expired_page_without_pay_url_has_no_button():
    html = _render("sub/expired.html", pay_url="", token=_TOKEN, web_url="")

    assert "Продлить подписку" not in html


def test_index_page_hides_button_when_web_exists():
    html = _render("subscription/index.html", pay_url=_PAY_URL, token=_TOKEN, web_url="https://cab.example.com")

    assert _PAY_URL not in html
