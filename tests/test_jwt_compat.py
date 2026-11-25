"""Старые подписки, ротация ключа и отказы JWT сохраняются после обновления."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_jwt_contract_with_real_dependencies():
    """Старые подписки, ротация ключа и отказы JWT сохраняются после обновления."""
    subprocess.run([sys.executable, str(Path(__file__).with_name("_dependency_probe.py")), "jwt"], check=True)
