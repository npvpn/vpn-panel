"""QR страницы подписки — scripts/qr-code.js (NPVPN-2368): исполняем настоящий скрипт в Node.

Код и логотип — одна картинка: на странице появляется только готовый canvas, сразу с логотипом
или (логотип не загрузился / не успел) без него, но не пустое место навсегда и не код, к которому
логотип дорисовывается потом. Обвязка tests/js/qr_code_harness.js подделывает DOM, qrcode.js,
Image и часы; Node есть на раннерах CI (ubuntu-latest).
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_HARNESS = Path(__file__).parent / "js" / "qr_code_harness.js"
_NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(_NODE is None, reason="нужен Node.js для исполнения qr-code.js")

# Рисуем в 2×: блок 200×200 на экране — canvas 400×400, логотип 56 → 112 по центру
_SIDE = 400
_LOGO_DRAW = ["logo", 144, 144, 112, 112]
_QR_COPY = ["qr-canvas", 0, 0]
# Сколько ждём логотип, прежде чем показать код без него (LOGO_WAIT_MS в qr-code.js)
_LOGO_WAIT_MS = 3000


def _run(*, canvas=True, logo="ok", logo_delay=0, logo_src=None, check_at=(0,)) -> dict:
    scenario = {"canvas": canvas, "logo": logo, "logoDelay": logo_delay, "checkAt": list(check_at)}
    if logo_src is not None:
        scenario["logoSrc"] = logo_src
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


def _shown(snapshot: dict) -> list[dict]:
    return snapshot["children"]


def test_qr_with_logo_appears_as_one_ready_image():
    out = _run(logo="ok", logo_delay=100, check_at=(50, 150))
    before, after = out["snapshots"]
    # пока логотип грузится — в блоке ничего, а не код без логотипа
    assert _shown(before) == []
    [image] = _shown(after)
    assert image["kind"] == "canvas"  # свой canvas, а не библиотечный (тот она потом прячет)
    assert (image["width"], image["height"]) == (_SIDE, _SIDE)
    assert image["draws"] == [_QR_COPY, _LOGO_DRAW]


def test_qr_drawn_offscreen_with_high_error_correction():
    out = _run()
    [call] = out["qrCalls"]
    assert call["into"] == "draft"
    assert call["text"] == "https://sub.example/sub/TOKEN/"
    assert (call["width"], call["height"]) == (_SIDE, _SIDE)
    assert call["correctLevel"] == 2  # H — восстанавливает закрытый логотипом центр
    assert out["logoRequested"] == "/statics/subscription/assets/qr-logo.png?v=1"


def test_logo_failed_shows_qr_without_logo():
    out = _run(logo="fail", logo_delay=10, check_at=(20,))
    [image] = _shown(out["snapshots"][0])
    assert image["draws"] == [_QR_COPY]


def test_logo_hanging_shows_qr_without_logo_after_timeout():
    out = _run(logo="hang", check_at=(_LOGO_WAIT_MS - 100, _LOGO_WAIT_MS + 100))
    waiting, shown = out["snapshots"]
    assert _shown(waiting) == []
    [image] = _shown(shown)
    assert image["draws"] == [_QR_COPY]


def test_late_logo_does_not_change_shown_image():
    # логотип пришёл после таймаута — уже показанную картинку не перерисовываем
    out = _run(logo="ok", logo_delay=_LOGO_WAIT_MS + 2000, check_at=(_LOGO_WAIT_MS + 100, _LOGO_WAIT_MS + 3000))
    for snapshot in out["snapshots"]:
        [image] = _shown(snapshot)
        assert image["draws"] == [_QR_COPY]


def test_without_logo_src_shows_qr_at_once():
    out = _run(logo_src="", check_at=(0,))
    [image] = _shown(out["snapshots"][0])
    assert image["draws"] == [_QR_COPY]
    assert out["logoRequested"] is None


def test_without_canvas_table_drawn_straight_into_block():
    # таблицу библиотека рисует прямо в блок 200×200 — размеры и отступы считает по нему
    out = _run(canvas=False, check_at=(0,))
    [call] = out["qrCalls"]
    assert call["into"] == "target"
    assert (call["width"], call["height"]) == (200, 200)
    [table] = _shown(out["snapshots"][0])
    assert table["kind"] == "table"
    assert out["logoRequested"] is None
