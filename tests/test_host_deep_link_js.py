"""Deep-link `#/?host=<username>` открывает модалку хостов на вкладке бота."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_PANEL = Path(__file__).resolve().parents[1]
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


def _plan(raw, bots: list[str]) -> dict:
    script = (
        "import { planHostDeepLink } from './app/dashboard/src/utils/hostDeepLink.ts';"
        "const [raw, bots] = JSON.parse(process.argv[1]);"
        "console.log(JSON.stringify(planHostDeepLink(raw, bots)));"
    )
    proc = subprocess.run(
        [_NODE, "--input-type=module", "-e", script, json.dumps([raw, bots])],
        cwd=_PANEL,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_known_bot_opens_by_bot_tab():
    assert _plan("@vpn_bot", ["other", "vpn_bot"]) == {
        "open": True,
        "tabIndex": 1,
        "selectedBot": "vpn_bot",
    }


def test_unknown_bot_opens_tab_with_empty_filter():
    assert _plan("missing", ["a", "b"]) == {"open": True, "tabIndex": 1, "selectedBot": ""}


def test_single_bot_opens_dialog_without_bot_tab():
    assert _plan("only", ["only"]) == {"open": True, "tabIndex": 0, "selectedBot": ""}


def test_empty_host_does_not_open():
    assert _plan("  ", ["a", "b"]) == {"open": False, "tabIndex": 0, "selectedBot": ""}


def _return_search(search: str) -> str:
    script = (
        "import { loginReturnSearch } from './app/dashboard/src/utils/loginReturn.ts';"
        "console.log(JSON.stringify(loginReturnSearch(process.argv[1])));"
    )
    proc = subprocess.run(
        [_NODE, "--input-type=module", "-e", script, search],
        cwd=_PANEL,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_login_keeps_host_and_drops_other_query():
    assert _return_search("?host=vpn%20bot&page=2") == "?host=vpn+bot"


def test_login_keeps_node_deep_link():
    assert _return_search("?node=11") == "?node=11"


def test_login_without_deep_link_keeps_nothing():
    assert _return_search("") == ""
