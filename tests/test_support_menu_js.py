"""Логика scripts/support-menu.js (NPVPN-2224): исполняем настоящий скрипт в Node.

Тесты шаблонов (test_subscription_support_menu.py) видят только разметку; здесь —
поведение: вход по ?support=open из VPN-приложения, прямой запуск чата без вилки,
одна видимая кнопка из двух на странице, сбой identity. Node есть на раннерах CI
(ubuntu-latest); зависимостей нет — обвязка tests/js/support_menu_harness.js
подделывает DOM, Chatwoot SDK и fetch сама.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_HARNESS = Path(__file__).parent / "js" / "support_menu_harness.js"
_NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(_NODE is None, reason="нужен Node.js для исполнения support-menu.js")

TG = "https://t.me/MyBot"


def _run(*, roots, search="", clicks=(), identity_ok=True) -> dict:
    scenario = {"search": search, "identityOk": identity_ok, "roots": roots, "clicks": list(clicks)}
    proc = subprocess.run(
        [_NODE, str(_HARNESS), json.dumps(scenario)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


# На странице две кнопки: плавающая и пункт нижнего меню / шапки — видна только одна.
def _two(mode, tg_url=TG):
    return [{"mode": mode, "tgUrl": tg_url, "visible": True}, {"mode": mode, "tgUrl": tg_url, "visible": False}]


def test_support_open_chat_mode_starts_chat_once():
    out = _run(roots=_two("chat", ""), search="?support=open")
    assert out["identityCalls"] == 1
    assert out["chatOpened"] is True
    assert out["setUser"]["identifier"] == "42"
    assert out["setUser"]["identifier_hash"] == "h"


def test_support_open_menu_mode_opens_only_visible_list():
    out = _run(roots=_two("menu"), search="?support=open")
    assert [r["listOpen"] for r in out["roots"]] == [True, False]
    assert out["identityCalls"] == 0
    assert out["chatOpened"] is False


def test_without_param_nothing_happens():
    out = _run(roots=_two("chat", ""))
    assert out["identityCalls"] == 0
    assert out["chatOpened"] is False
    assert [r["listOpen"] for r in out["roots"]] == [False, False]


def test_chat_mode_click_opens_chat_without_fork():
    out = _run(roots=_two("chat", ""), clicks=[[0, "toggle"]])
    assert out["identityCalls"] == 1
    assert out["chatOpened"] is True
    assert out["roots"][0]["listOpen"] is False


def test_menu_mode_click_opens_fork_then_chat_item_starts_chat():
    opened = _run(roots=_two("menu"), clicks=[[0, "toggle"]])
    assert opened["roots"][0]["listOpen"] is True
    assert opened["identityCalls"] == 0

    chat = _run(roots=_two("menu"), clicks=[[0, "toggle"], [0, "chat"]])
    assert chat["identityCalls"] == 1
    assert chat["chatOpened"] is True


def test_identity_failure_suggests_telegram_and_keeps_chat_closed():
    out = _run(roots=_two("menu"), clicks=[[0, "toggle"], [0, "chat"]], identity_ok=False)
    assert out["chatOpened"] is False
    assert out["roots"][0]["listOpen"] is True
    assert "Telegram" in out["roots"][0]["status"]


def test_identity_failure_chat_only_shows_error_without_telegram():
    out = _run(roots=_two("chat", ""), clicks=[[0, "toggle"]], identity_ok=False)
    assert out["chatOpened"] is False
    assert out["roots"][0]["listOpen"] is True
    assert out["roots"][0]["status"]
    assert "Telegram" not in out["roots"][0]["status"]
