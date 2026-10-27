from copy import deepcopy

import pytest


def preview(override=None, **kw):
    from app.xray.host_injection import diagnose_injection

    recipient = {"id": 9, "inbound_tag": "in", "host_injection": override, **kw}
    catalog = [
        {"id": 1, "inbound_tag": "in", "group_tag": "MAIN", "is_hidden": True},
        {"id": 2, "inbound_tag": "in", "group_tag": "MAIN", "is_disabled": True},
        {"id": 3, "inbound_tag": "in", "group_tag": "MAIN", "is_hidden": False},
    ]
    return diagnose_injection(recipient, catalog, lambda _: {}, {"in"})


def directive(selector=None, **kw):
    return {
        "injectHosts": [{"selector": selector or {"type": "tagRegex", "pattern": "^MAIN$"}, "tagPrefix": "proxy", **kw}]
    }


def codes(result):
    return {i.code for i in result.issues}


def test_unknown_tag_reports_group_and_no_sources():
    result = preview(directive({"type": "tagRegex", "pattern": "^TYPO$"}))
    assert codes(result) == {"empty_group", "empty_injection"}
    assert result.groups[0].group == 1
    assert result.groups[0].host_ids == []
    assert result.groups[0].pattern == "^TYPO$"


@pytest.mark.parametrize(("pool", "ids"), [("HIDDEN", [1]), ("NOT_HIDDEN", [3]), ("ALL", [1, 3])])
def test_hidden_sources_work_but_disabled_never_do(pool, ids):
    result = preview(directive(selectFrom=pool))
    assert result.groups[0].host_ids == ids
    assert not result.issues


def test_ids_explain_each_unavailable_source():
    result = preview(directive({"type": "ids", "values": [2, 3, 99, 9]}))
    assert {"disabled_source", "visibility_mismatch", "missing_source", "self_source", "empty_injection"} <= codes(
        result
    )
    assert {(i.code, i.host_id) for i in result.issues} >= {("disabled_source", 2), ("missing_source", 99)}


def test_invalid_regex_returns_path_without_echoing_input():
    result = preview(directive({"type": "tagRegex", "pattern": "["}))
    assert codes(result) == {"invalid_directive"}
    assert "pattern" in result.issues[0].path


def test_disabled_override_and_recipient_visibility():
    assert not preview({"enabled": False}).active
    result = preview(directive(), is_disabled=True, is_hidden=True)
    assert {"recipient_disabled", "recipient_hidden"} <= codes(result)


def test_virtual_source_and_duplicate_prefix():
    from app.xray.host_injection import diagnose_injection

    data = directive()
    data["injectHosts"] *= 2
    source = {"id": 1, "inbound_tag": "in", "group_tag": "MAIN", "is_hidden": True, "host_injection": directive()}
    before = deepcopy(source)
    result = diagnose_injection({"id": 9, "host_injection": data}, [source], lambda _: {}, {"in"})
    assert {"virtual_source", "duplicate_group_prefix", "empty_injection"} <= codes(result)
    assert source == before


def test_missing_inbound_and_invalid_source_template():
    from app.xray.host_injection import diagnose_injection

    hosts = [{"id": 1, "inbound_tag": "removed"}, {"id": 2, "inbound_tag": "in", "client_config_id": 2}]
    result = diagnose_injection(
        {"host_injection": directive({"type": "ids", "values": [1, 2]}, selectFrom="ALL")},
        hosts,
        lambda id_: {"npvpn": None} if id_ == 2 else {},
        {"in"},
    )
    assert {"inactive_inbound", "invalid_source", "empty_injection"} <= codes(result)


def test_selector_timeout_is_visible(monkeypatch):
    from app.xray import host_injection as module

    monkeypatch.setattr(
        module,
        "select_injected_hosts",
        lambda *a, **kw: (_ for _ in ()).throw(module.InjectionError("selector_timeout")),
    )
    assert "selector_timeout" in codes(preview(directive()))
