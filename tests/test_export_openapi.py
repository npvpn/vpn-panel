"""Схема OpenAPI собирается из кода и не открывает чужую базу."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def test_export_openapi_writes_admin_token(tmp_path: Path) -> None:
    destination = tmp_path / "openapi.json"
    env = os.environ.copy()
    env["SQLALCHEMY_DATABASE_URL"] = "mysql+pymysql://should-not-stick/db"
    probe = textwrap.dedent(
        """
        import runpy
        import sys

        sys.argv = ["export_openapi.py", sys.argv[1]]
        runpy.run_path("scripts/export_openapi.py", run_name="__main__")
        import config

        if config.SQLALCHEMY_DATABASE_URL != "sqlite://":
            raise SystemExit(config.SQLALCHEMY_DATABASE_URL)
        """
    )
    subprocess.run(
        [sys.executable, "-c", probe, str(destination)],
        cwd=_ROOT,
        check=True,
        env=env,
    )
    schema = json.loads(destination.read_text(encoding="utf-8"))
    assert schema["info"]["title"] == "MarzbanAPI"
    token = schema["paths"]["/api/admin/token"]["post"]
    assert token["operationId"]
