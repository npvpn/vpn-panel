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


def test_preview_preserves_draft_identity_and_excludes_connection_secrets():
    from app.models.host_injection import InjectionPreviewHost

    host = {
        "id": "rhf-generated",
        "host_id": 12,
        "inbound_tag": "VLESS",
        "group_tag": "edited",
        "is_hidden": True,
        "host_injection": {"enabled": False},
        "sni": "private",
        "password": "secret",
        "client_config_id": 4,
    }
    result = run_form(op="preview", host=host)
    validated = InjectionPreviewHost.model_validate(result)
    assert validated.id == 12 and validated.group_tag == "edited" and validated.is_hidden
    assert validated.host_injection == {"enabled": False} and validated.client_config_id == 4
    assert "sni" not in result and "password" not in result
    assert run_form(op="preview", host={"id": "new-rhf"})["id"] is None


def test_preview_only_complete_form_excludes_removed_hosts():
    data = {
        "op": "excluded",
        "saved": {"a": [{"id": 1}, {"id": 2}], "b": [{"id": 3}]},
        "rows": [{"host_id": 1}, {"host_id": 3}, {"id": "new-rhf"}],
    }
    assert run_form(**data, complete=True) == [2]
    assert run_form(**data, complete=False) == []


def test_preview_draft_order_matches_save_including_unsaved_rows():
    rows = [{"host_id": 3, "order": 9}, {"id": "new"}, {"host_id": 1, "order": 0}]
    assert [(h["id"], h["order"]) for h in run_form(op="drafts", rows=rows, complete=True)] == [(3, 0), (1, 2)]
    assert [(h["id"], h["order"]) for h in run_form(op="drafts", rows=rows, complete=False)] == [(3, 9), (1, 0)]
