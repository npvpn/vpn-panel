"""Выбор самостоятельных хостов и владение директивой инжекта."""

from copy import deepcopy
from time import monotonic

import pytest
from pydantic import ValidationError


def group(selector=None, **kw):
    from app.models.host_injection import InjectionGroup

    return InjectionGroup.model_validate(
        {"selector": selector or {"type": "tagRegex", "pattern": "^MAIN$"}, "tagPrefix": "proxy", **kw}
    )


def hosts():
    return [dict(id=i, remark=f"AU-{i}", group_tag="MAIN", is_hidden=i != 2, order=4 - i) for i in (1, 2, 3)]


def test_override_disable_alias_and_copy():
    from app.xray.host_injection import resolve_host_injection, strip_injection_directives

    block = {"injectHosts": [group().model_dump(mode="json")]}
    template = {"remnawave": block, "routing": {"rules": []}}
    before = deepcopy(template)
    assert resolve_host_injection(None, template).enabled
    assert resolve_host_injection({"enabled": False}, template) is None
    override = {"enabled": True, "injectHosts": [], "addVirtualHostAsOutbound": True}
    assert resolve_host_injection(override, template).addVirtualHostAsOutbound
    assert strip_injection_directives(template) == {"routing": {"rules": []}}
    assert template == before
    assert resolve_host_injection(None, {}) is None
    with pytest.raises(ValueError):
        resolve_host_injection(None, {"npvpn": block, "remnawave": block})


@pytest.mark.parametrize(("pool", "expected"), [("HIDDEN", [3, 1]), ("NOT_HIDDEN", [2]), ("ALL", [3, 2, 1])])
def test_pools_order_and_self_exclusion(pool, expected):
    from app.xray.host_injection import select_injected_hosts

    result = select_injected_hosts(group(selectFrom=pool), {"id": 99}, hosts(), deadline=monotonic() + 1)
    assert [h["id"] for h in result] == expected
    result = select_injected_hosts(group(selectFrom="ALL"), {"id": 2}, hosts(), deadline=monotonic() + 1)
    assert [h["id"] for h in result] == [3, 1]


@pytest.mark.parametrize("selector", [{"type": "remarkRegex", "pattern": "^AU-[13]$"}, {"type": "sameTagAsRecipient"}])
def test_regex_and_same_tag(selector):
    from app.xray.host_injection import select_injected_hosts

    result = select_injected_hosts(group(selector), {"id": 9, "group_tag": "MAIN"}, hosts(), deadline=monotonic() + 1)
    assert [h["id"] for h in result] == [3, 1]
    if selector["type"] == "sameTagAsRecipient":
        assert select_injected_hosts(group(selector), {"id": 9}, hosts(), deadline=monotonic() + 1) == []


def test_ids_keep_input_order_skip_missing_and_disabled():
    from app.xray.host_injection import select_injected_hosts

    source = hosts()
    source[2]["is_disabled"] = True
    result = select_injected_hosts(
        group({"type": "ids", "values": [1, 3, 2, 99]}, selectFrom="ALL"), {"id": 9}, source, deadline=monotonic() + 1
    )
    assert [h["id"] for h in result] == [1, 2]


@pytest.mark.parametrize(
    "data",
    [
        {"selector": {"type": "uuids", "values": ["uuid"]}},
        {"selector": {"type": "ids", "values": [True]}},
        {"selector": {"type": "ids", "values": [1, 1]}},
        {"selector": {"type": "ids", "values": list(range(1, 258))}},
        {"selector": {"type": "remarkRegex", "pattern": "["}},
        {"selector": {"type": "tagRegex", "pattern": "x" * 257}},
        {"useHostRemarkAsTag": True},
        {"unknown": True},
        {"tagPrefix": ""},
    ],
)
def test_invalid_groups(data):
    with pytest.raises(ValidationError):
        group(**data)


def test_bounds_and_disabled_override():
    from app.models.host_injection import HostInjection

    with pytest.raises(ValidationError):
        HostInjection(injectHosts=[group()] * 33)
    with pytest.raises(ValidationError):
        HostInjection(enabled=False, injectHosts=[group()])
    with pytest.raises(ValidationError):
        HostInjection(injectHosts=[])


def test_expired_deadline_and_pathological_regex():
    from app.xray.host_injection import InjectionError, select_injected_hosts

    with pytest.raises(InjectionError, match="timeout"):
        select_injected_hosts(group(), {"id": 9}, hosts(), deadline=monotonic() - 1)
    # A nested ambiguous match must never monopolize subscription generation.
    bad = group({"type": "remarkRegex", "pattern": "(a|aa)+$"})
    with pytest.raises(InjectionError, match="timeout"):
        select_injected_hosts(
            bad, {"id": 9}, [{"id": 1, "is_hidden": True, "remark": "a" * 510 + "!"}], deadline=monotonic() + 0.01
        )
