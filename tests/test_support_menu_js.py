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


def _run(
    *,
    roots,
    search="",
    clicks=(),
    identity_ok=True,
    chatwoot_error=False,
    last_token=None,
    sdk="present",
    ready_delay=0,
) -> dict:
    scenario = {
        "search": search,
        "identityOk": identity_ok,
        "chatwootError": chatwoot_error,
        "lastToken": last_token,
        "sdk": sdk,
        "readyDelay": ready_delay,
        "roots": roots,
        "clicks": list(clicks),
    }
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


# NPVPN-2256: Chatwoot отклонил пользователя (SET_USER_ERROR) — не оставляем открытым
# анонимный пустой чат, а закрываем его и предлагаем Telegram.
def test_chatwoot_rejects_user_chat_mode_closes_chat_and_suggests_telegram():
    out = _run(roots=_two("chat"), clicks=[(0, "toggle")], chatwoot_error=True)
    assert out["chatClosed"] is True
    assert out["roots"][0]["listOpen"] is True
    assert out["roots"][0]["status"] == "Чат недоступен, напишите в Telegram"


def test_chatwoot_rejects_user_menu_mode_reopens_list_with_error():
    out = _run(roots=_two("menu"), clicks=[(0, "toggle"), (0, "chat")], chatwoot_error=True)
    assert out["chatClosed"] is True
    # после успешного запуска список закрывался — ошибку надо показать, а не спрятать
    assert out["roots"][0]["listOpen"] is True
    assert out["roots"][0]["status"] == "Чат недоступен, напишите в Telegram"


# NPVPN-2256: в этом браузере раньше открывали другую подписку — переписку Chatwoot
# (cookie) забываем до запуска чата, чтобы не показать чужой чат на общем устройстве.
def test_other_subscription_before_forgets_previous_chat():
    out = _run(roots=_two("chat"), clicks=[(0, "toggle")], last_token="OTHER")
    assert set(out["cookiesCleared"]) == {"cw_conversation", "cw_user_wt"}
    assert out["storedToken"] == "TOKEN"
    assert out["chatOpened"] is True


def test_same_subscription_keeps_chat_history():
    out = _run(roots=_two("chat"), clicks=[(0, "toggle")], last_token="TOKEN")
    assert out["cookiesCleared"] == []
    assert out["chatOpened"] is True


# NPVPN-2256: пока грузится чат — спиннер на месте иконки нажатой кнопки, без «Загружаем чат…».
def test_chat_item_shows_spinner_while_loading():
    out = _run(roots=_two("menu"), clicks=[(0, "toggle"), (0, "chat")], ready_delay=500)
    assert out["roots"][0]["chatLoading"] is True
    assert out["roots"][0]["status"] == ""
    assert out["roots"][0]["listOpen"] is True
    assert out["chatOpened"] is False


def test_spinner_gone_after_chat_opens():
    out = _run(roots=_two("menu"), clicks=[(0, "toggle"), (0, "chat")])
    assert out["chatOpened"] is True
    assert out["roots"][0]["chatLoading"] is False
    assert out["roots"][0]["listOpen"] is False


# На кнопке «Помощь» лоадера нет — ни в вебе, ни в панели.
def test_chat_mode_no_spinner_on_help_button():
    out = _run(roots=_two("chat", ""), clicks=[(0, "toggle")], ready_delay=500)
    assert out["roots"][0]["toggleLoading"] is False
    assert out["roots"][0]["listOpen"] is False


# Ушли из меню, не дождавшись чата, — окно чата потом само не всплывает.
def test_escape_while_loading_does_not_open_chat_later():
    out = _run(roots=_two("menu"), clicks=[(0, "toggle"), (0, "chat"), (0, "escape")], ready_delay=30)
    assert out["setUser"] is not None
    assert out["chatOpened"] is False
    assert out["roots"][0]["listOpen"] is False
    assert out["roots"][0]["chatLoading"] is False


def test_telegram_while_loading_does_not_open_chat_later():
    out = _run(roots=_two("menu"), clicks=[(0, "toggle"), (0, "chat"), (0, "tg")], ready_delay=30)
    assert out["chatOpened"] is False
    assert out["roots"][0]["listOpen"] is False


# Скрипт чата не загрузился (например, 429) — не навсегда: следующий клик грузит его снова.
def test_sdk_load_failure_then_retry_loads_again():
    failed = _run(roots=_two("menu"), clicks=[(0, "toggle"), (0, "chat")], sdk="failOnce")
    assert failed["roots"][0]["status"] == "Чат недоступен, напишите в Telegram"
    assert failed["chatOpened"] is False

    retried = _run(roots=_two("menu"), clicks=[(0, "toggle"), (0, "chat"), (0, "chat")], sdk="failOnce")
    assert retried["scriptLoads"] == 2
    assert retried["chatOpened"] is True
    assert retried["roots"][0]["status"] == ""
