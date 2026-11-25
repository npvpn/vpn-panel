"""Существующие bcrypt/argon2 пароли и новые хеши переживают обновление backend."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_password_contract_with_real_dependencies():
    """Существующие bcrypt/argon2 пароли и новые хеши переживают обновление backend."""
    subprocess.run([sys.executable, str(Path(__file__).with_name("_dependency_probe.py")), "password"], check=True)
