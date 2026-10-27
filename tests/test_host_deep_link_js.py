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


def _settle(raw: str, bots: list[str]) -> dict:
    script = (
        "import { settleHostDeepLink } from './app/dashboard/src/utils/hostDeepLink.ts';"
        "const [raw, bots] = JSON.parse(process.argv[1]);"
        "console.log(JSON.stringify(settleHostDeepLink(raw, bots)));"
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


def test_hosts_arriving_after_empty_store_keeps_bot_tab():
    assert _settle("vpn_bot", ["other", "vpn_bot"]) == {
        "pending": False,
        "tabIndex": 1,
        "selectedBot": "vpn_bot",
    }


def test_pending_plan_survives_form_reset_before_hosts():
    script = (
        "import { applyHostDeepLinkWhenReady, resetHostsFormTab }"
        " from './app/dashboard/src/utils/hostDeepLink.ts';"
        "let ui = { pending: true, tabIndex: 1, selectedBot: 'vpn_bot' };"
        "ui = resetHostsFormTab(ui);"
        "ui = applyHostDeepLinkWhenReady(ui, {"
        " username: 'vpn_bot', botUsernames: ['other', 'vpn_bot'],"
        " auxLoading: false, hostsRequestSettled: false });"
        "console.log(JSON.stringify(ui));"
    )
    proc = subprocess.run(
        [_NODE, "--input-type=module", "-e", script],
        cwd=_PANEL,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == {
        "pending": True,
        "tabIndex": 1,
        "selectedBot": "vpn_bot",
    }


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


def _login_roundtrip(search: str, stale: str = "") -> dict:
    script = (
        "import { rememberLoginReturn, takeLoginReturn, LOGIN_RETURN_KEY }"
        " from './app/dashboard/src/utils/loginReturn.ts';"
        "const [search, stale] = JSON.parse(process.argv[1]);"
        "const box = new Map();"
        "const storage = {"
        " setItem: (k, v) => box.set(k, v),"
        " getItem: (k) => (box.has(k) ? box.get(k) : null),"
        " removeItem: (k) => box.delete(k),"
        "};"
        "if (stale) box.set(LOGIN_RETURN_KEY, stale);"
        "rememberLoginReturn(search, storage);"
        "const kept = box.get(LOGIN_RETURN_KEY) ?? '';"
        "const taken = takeLoginReturn(storage);"
        "console.log(JSON.stringify({ kept, taken, left: box.size }));"
    )
    proc = subprocess.run(
        [_NODE, "--input-type=module", "-e", script, json.dumps([search, stale])],
        cwd=_PANEL,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_login_stores_host_and_restores_it_once():
    assert _login_roundtrip("?host=vpn_bot&page=2") == {
        "kept": "?host=vpn_bot",
        "taken": "?host=vpn_bot",
        "left": 0,
    }


def test_login_stores_node_deep_link():
    assert _login_roundtrip("?node=11") == {
        "kept": "?node=11",
        "taken": "?node=11",
        "left": 0,
    }


def test_login_without_deep_link_clears_return_and_opens_dashboard():
    assert _login_roundtrip("", stale="?host=old") == {
        "kept": "",
        "taken": "",
        "left": 0,
    }
