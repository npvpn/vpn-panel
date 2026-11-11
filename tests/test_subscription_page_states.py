"""Состояния страницы подписки внутри index.html (NPVPN-2315).

expired / limited / revoked.html — обёртки: задают page_state и включают index.html. Маршрут
по-прежнему выбирает их по имени, поэтому своя папка шаблонов со старыми полными страницами
продолжает работать; здесь проверяем встроенные.
"""

from __future__ import annotations

import pathlib
import re

import jinja2
import pytest

_ROOT = pathlib.Path(__file__).parent.parent
_DIR = _ROOT / "app" / "templates" / "subscription"
_CABINET = "https://cab.example.com"


def _render(template: str, *, web_url: str = _CABINET, pay_url: str = "") -> str:
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(_DIR)), undefined=jinja2.ChainableUndefined)
    ctx = {
        "pay_url": pay_url,
        "token": "TOKEN",
        "devices_json": "[]",
        "client_apps": {},
        "user": {},
        "devices": [],
        "sub_path": "sub",
        "web_url": web_url,
        "bot_url": "",
        "show_ads": True,
        "sub_statics": "/statics/subscription/",
        "support": {"mode": "none"},
    }
    return env.get_template(template).render(ctx)


def _start_tab(html: str) -> str:
    match = re.search(r"currentPage: '(\w+)'", html)
    assert match, "нет вкладки по умолчанию"
    return match.group(1)


def _poll_script(html: str) -> str | None:
    match = re.search(r'<script defer src="[^"]*status-poll\.js(?:\?v=[^"]*)?"(.*?)></script>', html, re.S)
    return match.group(1) if match else None


@pytest.mark.parametrize("state", ["expired", "limited", "revoked"])
def test_state_page_is_index_with_sidebar_and_bottom_menu(state):
    html = _render(f"{state}.html")
    assert f"pageState: '{state}'" in html
    assert '<aside  side class="sidebar">' in html
    assert '<nav class="floating-nav">' in html


@pytest.mark.parametrize(
    ("template", "tab"),
    [("index.html", "settings"), ("expired.html", "tariff"), ("revoked.html", "tariff"), ("limited.html", "devices")],
)
def test_start_tab_matches_mockup(template, tab):
    assert _start_tab(_render(template)) == tab


def test_regular_page_has_no_state_card():
    # до лимита подсказки «подключить больше устройств» нет — только на странице лимита
    html = _render("index.html")
    assert "pageState: ''" in html
    assert "state-card" not in html


def _fallback(html: str) -> str:
    match = re.search(r'<div class="state-fallback">(.*?)</main>', html, re.S)
    assert match, "нет заглушки «Настроек»"
    return match.group(1)


@pytest.mark.parametrize(
    ("template", "title", "button"),
    [
        ("revoked.html", "Ключ доступа устарел", "data-cabinet-link>Войти в личный кабинет"),
        ("expired.html", "Подписка истекла", 'href="https://pay.example/TOKEN" class="primary-btn"'),
        ("limited.html", "Лимит устройств достигнут", "data-cabinet-link>Войти в личный кабинет"),
    ],
)
def test_settings_replaced_by_fallback_in_states(template, title, button):
    # QR и инструкции в состояниях не сработают — вместо них заглушка с действием
    html = _render(template, pay_url="https://pay.example")
    assert 'id="qrcode-main"' not in html
    fallback = _fallback(html)
    assert f">{title}<" in fallback
    assert button in fallback


def test_regular_page_keeps_settings():
    html = _render("index.html")
    assert 'id="qrcode-main"' in html
    assert "state-fallback" not in html


def test_apple_region_notice_only_on_apple_tabs():
    """NPVPN-2362: на iOS и Mac до кнопок скачивания — ссылка на инструкцию смены региона App Store."""
    html = _render("index.html")
    notice = re.search(r'<template x-if="([^"]*)">\s*<div class="setup-notice">(.*?)</template>', html, re.S)
    assert notice, "нет подсказки о смене региона"
    assert notice.group(1) == "currentPlatform === 'ios' || currentPlatform === 'macos'"
    assert 'href="https://happ.info/ru/apple-region/"' in notice.group(2)
    assert html.index('class="setup-notice"') < html.index('class="app-chips"')


def test_expired_fallback_without_pay_leads_to_cabinet():
    fallback = _fallback(_render("expired.html"))
    assert "Оплатить" not in fallback
    assert 'class="primary-btn" data-cabinet-link>Войти в личный кабинет' in fallback


def test_fallback_without_cabinet_has_no_button():
    assert "<a " not in _fallback(_render("revoked.html", web_url=""))


def test_revoked_card_on_tariff():
    html = _render("revoked.html")
    assert html.count('class="state-card"') == 1
    assert "вставьте новый ключ" in html
    assert ">Ключ доступа устарел<" in html


def test_expired_card_on_tariff_with_pay_and_cabinet():
    html = _render("expired.html", pay_url="https://pay.example")
    assert html.count('class="state-card"') == 1
    assert "Подписка истекла&nbsp;— оплатите её" in html
    assert 'href="https://pay.example/TOKEN" class="primary-btn"' in html
    assert ">Подписка истекла<" in html


def test_expired_without_pay_url_makes_cabinet_primary():
    html = _render("expired.html")
    assert "Оплатить" not in html
    assert 'class="primary-btn" data-cabinet-link>Войти в личный кабинет' in html


def test_card_without_cabinet_link_has_no_cabinet_button():
    html = _render("revoked.html", web_url="")
    assert "state-card" in html
    assert "data-cabinet-link>Войти в личный кабинет" not in html


@pytest.mark.parametrize(
    ("template", "with_cabinet", "without_cabinet"),
    [
        (
            "revoked.html",
            ["для этого войдите в&nbsp;личный кабинет", "Войдите в&nbsp;личный кабинет, чтобы получить новый ключ"],
            ["вставьте новый ключ в&nbsp;приложение</p>", "Получите новый ключ, чтобы подключить устройство"],
        ),
        (
            "limited.html",
            ["Чтобы подключить больше устройств&nbsp;— войдите", "увеличьте лимит в&nbsp;личном кабинете"],
            [
                "удалите одно из&nbsp;подключённых",
                "Удалите одно из&nbsp;подключённых устройств, чтобы подключить новое",
            ],
        ),
    ],
)
def test_texts_mention_cabinet_only_when_it_exists(template, with_cabinet, without_cabinet):
    # без web_url и bot_url кнопки входа нет — тексты не должны отправлять в кабинет
    html = _render(template)
    assert all(text in html for text in with_cabinet)
    assert not any(text in html for text in without_cabinet)
    html = _render(template, web_url="")
    assert "личн" not in html.split('class="state-card__text"', 1)[1].split("</p>", 1)[0]
    assert "личн" not in _fallback(html).split('class="state-fallback__text"', 1)[1].split("</p>", 1)[0]
    assert all(text in html for text in without_cabinet)


def test_limited_shows_limit_and_hides_add_device():
    html = _render("limited.html")
    assert "&nbsp;— лимит устройств достигнут" in html
    assert "Добавить устройства" not in html
    assert "Чтобы подключить больше устройств" in html
    assert html.count('class="state-card"') == 1
    # перезагрузка после удаления — только когда устройств стало меньше лимита (как «cleared» опроса)
    assert "this.devices.length < this.deviceLimit" in html


@pytest.mark.parametrize(
    ("template", "expected", "absent"),
    [
        # обычная: перезагрузка при достижении лимита и при отзыве токена
        ("index.html", ['data-device-limit-mode="reached"', 'data-reload-on-gone="true"'], []),
        # лимит: перезагрузка, когда устройство освободилось; «reached» здесь перезагружал бы вечно
        ("limited.html", ['data-device-limit-mode="cleared"'], ["reached", "data-reload-on-gone"]),
        # истекла: только смена статуса
        ("expired.html", [], ["data-device-limit-mode", "data-reload-on-gone"]),
    ],
)
def test_status_poll_matches_state(template, expected, absent):
    poll = _poll_script(_render(template))
    assert poll is not None
    for attr in expected:
        assert attr in poll
    for attr in absent:
        assert attr not in poll


def test_revoked_does_not_poll_status():
    # /info на отозванном токене отвечает 404 — опрос с reload-on-gone перезагружал бы страницу вечно
    assert _poll_script(_render("revoked.html")) is None


def test_tariff_card_rows_from_mockup():
    html = _render("index.html")
    card = re.search(r'<dl class="tariff-card__rows">(.*?)</dl>', html, re.S)
    assert card
    labels = re.findall(r"<dt[^>]*>(.*?)</dt>", card.group(1))
    assert labels == ["ID", "Статус", "Трафик (белый список)", "Срок действия", "Устройства"]
    assert "Ваш тариф" not in html


@pytest.mark.parametrize(
    ("template", "has_title"),
    [("index.html", False), ("limited.html", False), ("expired.html", True), ("revoked.html", True)],
)
def test_tariff_card_title_only_under_other_page_title(template, has_title):
    # заголовок страницы «Тариф» — без второго «Тариф» в карточке
    assert ('<h3 class="tariff-card__title">Тариф</h3>' in _render(template)) is has_title


def test_device_delete_icon_is_cross():
    html = _render("index.html")
    assert 'd="M7 7L12 12M12 12L17 17M12 12L7 17M12 12L17 7"' in html
    assert "clip0_5280_1914" not in html


def _settings_header(html: str) -> str:
    # шапка «Настроек» — от её блока до шапки «Тарифа»
    start = html.index('x-show="currentPage === \'settings\'" class="page-header')
    return html[start : html.index('x-show="currentPage === \'tariff\'" class="page-header', start)]


@pytest.mark.parametrize(
    ("template", "pay_url", "has_cabinet_icon"),
    [
        ("index.html", "", True),
        # в заглушке кнопка «Войти в личный кабинет» — иконку кабинета в шапке не дублируем
        ("revoked.html", "", False),
        ("limited.html", "", False),
        ("expired.html", "", False),
        # в заглушке «Оплатить» — кабинет остаётся в шапке
        ("expired.html", "https://pay.example", True),
    ],
)
def test_settings_header_cabinet_icon_not_duplicated(template, pay_url, has_cabinet_icon):
    header = _settings_header(_render(template, pay_url=pay_url))
    assert ('class="header-account-btn"' in header) is has_cabinet_icon


@pytest.mark.parametrize(
    ("template", "can_delete"),
    [("index.html", True), ("limited.html", True), ("expired.html", False), ("revoked.html", False)],
)
def test_device_delete_only_where_server_allows(template, can_delete):
    # ключ устарел / подписка истекла — сервер отклоняет удаление (403), крестик не показываем
    assert ('class="device-card__delete"' in _render(template)) is can_delete


def test_tariff_device_count_is_live():
    # после удаления устройства счётчик на «Тарифе» обновляется без перезагрузки
    assert 'x-text="deviceLimit > 0 ? `${deviceCount} из ${deviceLimit}` : deviceCount"' in _render("index.html")


def test_linux_command_only_for_deb():
    # apt install — только для .deb; адрес и имя файла в кавычках (getter linuxInstallCommand)
    html = _render("index.html")
    assert "selectedOs === 'Linux' && linuxDebUrl" in html
    assert 'x-text="linuxInstallCommand"' in html
