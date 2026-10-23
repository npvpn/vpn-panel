"""Zod и сервер разделяют контракт группы и режима композиции."""

import json
import subprocess

import pytest

from app.models.host_injection import HostInjection
from tests.test_host_balancing_form import NODE, ROOT
from tests.test_host_balancing_form import pytestmark as pytestmark


def run_form(**data):
    result = subprocess.run(
        [NODE, str(ROOT / "tests/js/host_injection_harness.mjs"), json.dumps(data)],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize(
    "selector",
    [
        {"type": "ids", "values": [2, 1]},
        {"type": "remarkRegex", "pattern": "^AU"},
        {"type": "tagRegex", "pattern": "^MAIN$"},
        {"type": "sameTagAsRecipient"},
    ],
)
def test_injection_schema_matches_backend(selector):
    value = {"injectHosts": [{"selector": selector, "tagPrefix": "proxy", "selectFrom": "ALL"}]}
    result = run_form(op="validate", value=value)
    assert result["success"]
    assert result["data"] == HostInjection.model_validate(value).model_dump(mode="json")


@pytest.mark.parametrize("value", [{"enabled": False}, {"injectHosts": [], "addVirtualHostAsOutbound": True}])
def test_disabling_and_own_connection(value):
    result = run_form(op="validate", value=value)
    assert result["success"] and result["data"] == HostInjection.model_validate(value).model_dump(mode="json")


@pytest.mark.parametrize(
    "value",
    [
        {"injectHosts": []},
        {"injectHosts": [{"selector": {"type": "ids", "values": [1, 1]}, "tagPrefix": "proxy"}]},
        {"injectHosts": [{"selector": {"type": "ids", "values": [1]}, "tagPrefix": "proxy", "useHostTagAsTag": True}]},
    ],
)
def test_rejects_invalid_groups(value):
    assert not run_form(op="validate", value=value)["success"]


def test_effective_mode_uses_selected_default_and_form_precedence():
    templates = [
        {"id": 1, "slug": "default", "body": json.dumps({"npvpn": {"addVirtualHostAsOutbound": True}})},
        {"id": 2, "slug": "other", "body": "{}"},
    ]
    assert run_form(op="effective", host={"host_injection": None}, templates=templates)["enabled"]
    assert run_form(op="effective", host={"host_injection": {"enabled": False}}, templates=templates) is None
    assert run_form(op="effective", host={"client_config_id": 2}, templates=templates) is None


def test_file_template_injection_comes_from_server_metadata():
    directive = HostInjection(addVirtualHostAsOutbound=True).model_dump(mode="json")
    templates = [
        {"id": 1, "slug": "default", "body": "", "effective_injection": directive},
        {"id": 2, "slug": "empty", "body": "", "effective_injection": directive},
        {"id": 3, "slug": "ordinary", "body": "{}", "effective_injection": None},
    ]
    for selected in (None, 1, 2):
        assert run_form(op="effective", host={"client_config_id": selected}, templates=templates) == directive
    assert run_form(op="effective", host={"client_config_id": 3}, templates=templates) is None
