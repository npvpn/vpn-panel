"""Пороги соло-панели в дашборде (NPVPN-2244). Node исполняет .ts без сборки."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_HARNESS = Path(__file__).parent / "js" / "bot_audience_harness.mjs"
_NODE = shutil.which("node")


def _node_strips_types() -> bool:
    if _NODE is None:
        return False
    proc = subprocess.run(
        [_NODE, "-p", "Boolean(process.features.typescript)"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return proc.stdout.strip() == "true"


pytestmark = pytest.mark.skipif(not _node_strips_types(), reason="нужен Node.js ≥ 22.18 (исполняет .ts без сборки)")


def _run(scenario: dict) -> dict:
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


def test_flags():
    assert _run({"op": "flags", "botCount": 0}) == {"solo": True, "single": True}
    assert _run({"op": "flags", "botCount": 1}) == {"solo": False, "single": True}
    assert _run({"op": "flags", "botCount": 2}) == {"solo": False, "single": False}


def test_preview_skips_bot_filter_until_two_bots():
    hosts = [
        {"remark": "free", "is_disabled": False, "bot_usernames": []},
        {"remark": "off", "is_disabled": True, "bot_usernames": []},
        {"remark": "apple", "bot_usernames": ["apple"]},
    ]
    assert _run({"op": "preview", "hosts": hosts, "botCount": 0, "botUsername": ""})["remarks"] == [
        "free",
        "apple",
    ]
    assert _run({"op": "preview", "hosts": hosts, "botCount": 1, "botUsername": "apple"})["remarks"] == [
        "free",
        "apple",
    ]
    assert _run({"op": "preview", "hosts": hosts, "botCount": 2, "botUsername": "apple"})["remarks"] == ["apple"]
