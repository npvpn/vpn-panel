"""Схема OpenAPI собирается из кода и содержит вход администратора."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def test_export_openapi_writes_admin_token(tmp_path: Path) -> None:
    destination = tmp_path / "openapi.json"
    subprocess.run(
        [sys.executable, "scripts/export_openapi.py", str(destination)],
        cwd=_ROOT,
        check=True,
    )
    schema = json.loads(destination.read_text(encoding="utf-8"))
    assert "/api/admin/token" in schema["paths"]
