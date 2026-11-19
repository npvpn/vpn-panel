"""Обновление FastAPI/Pydantic сохраняет вход и создание/продление пользователя."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_real_api_authentication_and_user_extension():
    """Настоящие роутеры и CRUD сохраняют контракт HTTP и данные пользователя."""
    subprocess.run([sys.executable, str(Path(__file__).with_name("_dependency_probe.py")), "api"], check=True)
