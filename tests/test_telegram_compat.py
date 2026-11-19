"""Обновлённый Telegram SDK регистрирует обработчики и отсекает неподходящие callback."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("scenario", ["telegram_filters", "telegram_registration"])
def test_telegram_sdk_contract(scenario):
    """Входной контракт panel проверяется настоящими объектами и регистрацией SDK."""
    subprocess.run([sys.executable, str(Path(__file__).with_name("_dependency_probe.py")), scenario], check=True)
