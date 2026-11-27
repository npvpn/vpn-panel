"""Сценарии настроек сервиса на настоящем TypeScript-модуле дашборда."""

import shutil
import subprocess
from pathlib import Path

import pytest

_HARNESS = Path(__file__).parent / "js" / "bot_settings_harness.mjs"


def test_bot_settings_dialog_logic():
    node = shutil.which("node")
    if not node:
        pytest.skip("нужен Node.js ≥ 22.18 (исполняет .ts без сборки)")
    support = subprocess.run(
        [node, "-p", "Boolean(process.features.typescript)"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if support.stdout.strip() != "true":
        pytest.skip("нужен Node.js ≥ 22.18 (исполняет .ts без сборки)")

    result = subprocess.run(
        [node, "--test", str(_HARNESS)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
