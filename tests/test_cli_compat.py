"""CLI и lifecycle панели работают на обновлённых Typer и APScheduler."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("scenario", ["cli", "lifecycle"])
def test_real_dependency_contract(scenario):
    """CLI и lifecycle панели работают на обновлённых Typer и APScheduler."""
    subprocess.run([sys.executable, str(Path(__file__).with_name("_dependency_probe.py")), scenario], check=True)
