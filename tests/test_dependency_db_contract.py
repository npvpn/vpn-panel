"""SQLAlchemy сохраняет транзакции и явный autoflush=False панели."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_db_contract_with_real_dependencies():
    """SQLAlchemy сохраняет транзакции и явный autoflush=False панели."""
    subprocess.run([sys.executable, str(Path(__file__).with_name("_dependency_probe.py")), "db"], check=True)
