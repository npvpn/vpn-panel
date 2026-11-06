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
    storage_broken=False,
    storage_full=False,
    other_tab_during_load=False,
    sdk="present",
    ready_delay=0,
    settle=0,
    error_delay=0,
) -> dict:
    scenario = {
        "search": search,
        "identityOk": identity_ok,
        "chatwootError": chatwoot_error,
        "lastToken": last_token,
        "storageBroken": storage_broken,
        "storageFull": storage_full,
        "otherTabDuringLoad": other_tab_during_load,
        "sdk": sdk,
        "readyDelay": ready_delay,
        "settle": settle,
        "errorDelay": error_delay,
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


def test_support_open_menu_survives_click_outside():
    # пришли по ссылке за поддержкой — случайный клик по странице меню не закрывает
    out = _run(roots=_two("menu"), search="?support=open", clicks=[(0, "outside")])
    assert out["roots"][0]["listOpen"] is True


@pytest.mark.parametrize("target", ["toggle", "escape"])
def test_support_open_menu_closes_explicitly(target):
    out = _run(roots=_two("menu"), search="?support=open", clicks=[(0, target)])
    assert out["roots"][0]["listOpen"] is False


def test_support_open_menu_after_reopen_closes_on_click_outside():
    # закрыли и открыли снова кнопкой — дальше как обычно
    out = _run(roots=_two("menu"), search="?support=open", clicks=[(0, "toggle"), (0, "toggle"), (0, "outside")])
    assert out["roots"][0]["listOpen"] is False


def test_menu_opened_by_toggle_closes_on_click_outside():
    out = _run(roots=_two("menu"), clicks=[(0, "toggle"), (0, "outside")])
    assert out["roots"][0]["listOpen"] is False


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


# Первый заход после выкладки: токена ещё нет, а cookie Chatwoot могли остаться от другой
# подписки — чья сессия, не знаем, поэтому забываем.
def test_no_saved_subscription_forgets_chat_session():
    out = _run(roots=_two("chat"), clicks=[(0, "toggle")], last_token=None)
    assert set(out["cookiesCleared"]) == {"cw_conversation", "cw_user_wt"}
    assert out["storedToken"] == "TOKEN"
    assert out["chatOpened"] is True


# localStorage недоступен (приватный режим) — проверить подписку нечем: сессию забываем,
# чат всё равно открывается.
def test_storage_unavailable_forgets_chat_session_and_chat_still_works():
    out = _run(roots=_two("chat"), clicks=[(0, "toggle")], storage_broken=True)
    assert set(out["cookiesCleared"]) == {"cw_conversation", "cw_user_wt"}
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


# На самой кнопке поддержки лоадера нет — ни в вебе, ни в панели.
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


# Пока грузился скрипт чата, другая вкладка открыла чат своей подписки — cookie уже её.
# Проверка идёт вплотную к run(), поэтому чужую сессию забываем и здесь.
def test_other_tab_switched_subscription_while_sdk_loading_forgets_session():
    out = _run(roots=_two("chat"), clicks=[(0, "toggle")], last_token="TOKEN", sdk="load", other_tab_during_load=True)
    assert set(out["cookiesCleared"]) == {"cw_conversation", "cw_user_wt"}
    assert out["storedToken"] == "TOKEN"
    assert out["chatOpened"] is True


# Записать подписку не удалось (хранилище переполнено) — старую запись удаляем, иначе в следующий
# раз чужую сессию приняли бы за сессию той подписки.
def test_failed_to_save_subscription_removes_stale_record():
    out = _run(roots=_two("chat"), clicks=[(0, "toggle")], last_token="OTHER", storage_full=True)
    assert set(out["cookiesCleared"]) == {"cw_conversation", "cw_user_wt"}
    assert out["storedToken"] is None
    assert out["chatOpened"] is True


# Ушли из меню, не дождавшись чата, а потом Chatwoot отклонил пользователя — меню само не открывается.
def test_chatwoot_error_after_leaving_menu_does_not_reopen_it():
    out = _run(
        roots=_two("menu"), clicks=[(0, "toggle"), (0, "chat"), (0, "escape")], chatwoot_error=True, ready_delay=30
    )
    assert out["chatOpened"] is False
    assert out["roots"][0]["listOpen"] is False


# NPVPN-2314: шторка «Как хотите связаться» — значок в шапке на мобилке при обоих способах.
def _sheet():
    return [{"mode": "menu", "tgUrl": TG, "visible": True, "sheet": True}]


def test_sheet_opens_locks_page_and_focuses_close():
    out = _run(roots=_sheet(), clicks=[(0, "toggle")])
    assert out["roots"][0]["listOpen"] is True
    assert out["bodyLocked"] is True
    assert out["focus"] == "close"


@pytest.mark.parametrize("target", ["close", "overlay", "escape"])
def test_sheet_closes_unlocks_page_and_returns_focus(target):
    out = _run(roots=_sheet(), clicks=[(0, "toggle"), (0, target), (0, "wait")])
    root = out["roots"][0]
    assert root["listOpen"] is False
    assert root["closing"] is False
    assert out["bodyLocked"] is False
    assert out["focus"] == "toggle"


def test_sheet_from_link_survives_overlay_tap_but_closes_by_cross():
    out = _run(roots=_sheet(), search="?support=open", clicks=[(0, "overlay")])
    assert out["roots"][0]["listOpen"] is True
    out = _run(roots=_sheet(), search="?support=open", clicks=[(0, "close"), (0, "wait")])
    assert out["roots"][0]["listOpen"] is False


def test_sheet_slides_away_before_hiding():
    # уезжает анимацией: сразу после закрытия ещё в DOM, но прокрутка страницы уже вернулась
    out = _run(roots=_sheet(), clicks=[(0, "toggle"), (0, "close")])
    assert out["roots"][0]["listOpen"] is True
    assert out["roots"][0]["closing"] is True
    assert out["bodyLocked"] is False


def test_toggle_while_sheet_slides_away_opens_it_again():
    out = _run(roots=_sheet(), clicks=[(0, "toggle"), (0, "close"), (0, "toggle")], settle=400)
    root = out["roots"][0]
    assert root["listOpen"] is True
    assert root["closing"] is False
    assert out["bodyLocked"] is True


def test_tab_stays_inside_sheet():
    # фокус на крестике (первый); Shift+Tab — на последний пункт, Tab с него — снова на крестик
    back = _run(roots=_sheet(), clicks=[(0, "toggle"), (0, "shiftTab")])
    assert back["focus"] == "tg"
    forward = _run(roots=_sheet(), clicks=[(0, "toggle"), (0, "shiftTab"), (0, "tab")])
    assert forward["focus"] == "close"


def test_sheet_closes_when_window_becomes_desktop():
    out = _run(roots=_sheet(), clicks=[(0, "toggle"), (0, "desktop"), (0, "wait")])
    assert out["roots"][0]["listOpen"] is False
    assert out["bodyLocked"] is False


def test_chat_from_sheet_closes_it():
    out = _run(roots=_sheet(), clicks=[(0, "toggle"), (0, "chat")], settle=400)
    assert out["chatOpened"] is True
    assert out["roots"][0]["listOpen"] is False
    assert out["bodyLocked"] is False


def test_floating_menu_does_not_lock_page():
    out = _run(roots=_two("menu"), clicks=[(0, "toggle")])
    assert out["roots"][0]["listOpen"] is True
    assert out["bodyLocked"] is False


def test_tab_moves_through_sheet_items():
    # крестик → «Написать в чат» → «Связаться в Telegram» — обычный Tab внутри шторки не перехватывается
    to_chat = _run(roots=_sheet(), clicks=[(0, "toggle"), (0, "tab")])
    assert to_chat["focus"] == "chat"
    to_tg = _run(roots=_sheet(), clicks=[(0, "toggle"), (0, "tab"), (0, "tab")])
    assert to_tg["focus"] == "tg"


def test_chat_error_after_resize_to_desktop_does_not_lock_page():
    # ошибка Chatwoot пришла, когда окно уже расширили до ПК: шторка там скрыта —
    # открывать её и блокировать прокрутку страницы нельзя
    out = _run(
        roots=_sheet(),
        clicks=[(0, "toggle"), (0, "chat"), (0, "desktop")],
        chatwoot_error=True,
        error_delay=60,
        settle=400,
    )
    assert out["bodyLocked"] is False


def test_focus_not_returned_to_hidden_icon_on_desktop():
    # шторка закрылась из-за расширения до ПК — значок в шапке скрыт, фокус на него не ставим
    out = _run(roots=_sheet(), clicks=[(0, "toggle"), (0, "desktop"), (0, "wait")])
    assert out["roots"][0]["listOpen"] is False
    assert out["focus"] != "toggle"
