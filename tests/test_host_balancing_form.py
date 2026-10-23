"""Контракт формы: настоящие Zod-схемы, roundtrip API и невалидные значения."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.models.host_balancing import HostBalancing
from tests.test_hosts_dialog_logic_js import _node_strips_types

ROOT = Path(__file__).parents[1]
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(
    not _node_strips_types() or not (ROOT / "app/dashboard/node_modules/zod").exists(),
    reason="Node with native TypeScript support and dashboard dependencies required",
)


def run_form(**payload):
    result = subprocess.run(
        [NODE, str(ROOT / "tests/js/host_balancing_harness.mjs"), json.dumps(payload)],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize("strategy", ["random", "roundRobin", "leastPing", "leastLoad"])
def test_form_defaults_match_backend(strategy):
    result = run_form(op="default", strategy=strategy)
    assert result == HostBalancing(strategy=strategy).model_dump(mode="json")


@pytest.mark.parametrize(
    "field,value",
    [
        ("expected", -1),
        ("expected", 1.5),
        ("tolerance", 1.1),
        ("maxRTT", "garbage"),
        ("baselines", ["0s"]),
        ("costs", [{"match": "", "regexp": False, "value": 1}]),
    ],
)
def test_form_rejects_invalid_leastload(field, value):
    balancing = HostBalancing(strategy="leastLoad").model_dump(mode="json")
    balancing["settings"][field] = value
    assert not run_form(op="validate", balancing=balancing)["success"]


def test_form_selected_nodes_override_empty_legacy_fields_and_roundtrip():
    host = dict(
        inbound_tag="VLESS",
        order=0,
        remark="RU → NL",
        address="",
        port=None,
        path=None,
        sni=None,
        host=None,
        fragment_setting=None,
        noise_setting=None,
        security="inbound_default",
        alpn="",
        fingerprint="",
        node_ids=[],
        balancer_nodes_source="selected",
        balancer_node_ids=[1, 2],
        balancing=HostBalancing(strategy="leastLoad").model_dump(mode="json"),
    )
    parsed = run_form(op="host", host=host)
    assert parsed["success"]
    assert parsed["data"]["balancing"] == host["balancing"]
    assert parsed["data"]["balancer_node_ids"] == [1, 2]
    assert parsed["data"]["node_ids"] == []
    host["balancer_node_ids"] = []
    assert not run_form(op="host", host=host)["success"]
    host["host_id"] = 55  # empty after deletion may still be edited
    assert run_form(op="host", host=host)["success"]
    host["balancer_nodes_source"] = "host"
    assert not run_form(op="host", host=host)["success"]


def test_form_warns_when_selected_pool_has_no_active_members():
    assert not run_form(op="pool", ids=[1, 2], nodes=[{"id": 1, "status": "disabled"}, {"id": 2, "status": "disabled"}])
    assert not run_form(op="pool", ids=[1], nodes=[])
    assert run_form(op="pool", ids=[1, 2], nodes=[{"id": 1, "status": "disabled"}, {"id": 2, "status": "error"}])
