"""Контракт настройки, входного пула и клиентской балансировки."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.models.host_balancing import HostBalancing
from app.models.node import NodeStatus
from app.xray.host_addresses import (
    addresses_from_nodes,
    host_has_bs_node,
    resolve_host_addresses,
    resolve_host_node_ids,
)
from app.xray.host_balancer import apply_host_balancer


def node(n, *, bs=False, disabled=False):
    return SimpleNamespace(
        id=n, address=f"192.0.2.{n}", is_bs=bs, status=NodeStatus.disabled if disabled else NodeStatus.connected
    )


def host(selected):
    return SimpleNamespace(
        address="downstream.example", nodes=[node(90)], balancer_nodes_source="selected", balancer_nodes=selected
    )


def test_entry_pool_is_independent_and_overrides_static_address():
    h = host([node(2, bs=True), node(1)])
    assert resolve_host_addresses(h) == ["192.0.2.1", "192.0.2.2"]
    assert resolve_host_node_ids(h) == [1, 2]
    assert addresses_from_nodes(h)
    assert host_has_bs_node(h)
    h.nodes = [node(91)]
    assert resolve_host_node_ids(h) == [1, 2]


def test_empty_explicit_pool_does_not_fall_back_to_downstream():
    h = host([node(1, bs=True, disabled=True)])
    assert resolve_host_addresses(h) == []
    assert resolve_host_node_ids(h) == []
    assert not host_has_bs_node(h)


def test_downstream_bs_does_not_mark_entry_pool():
    h = host([node(1)])
    h.nodes = [node(90, bs=True)]
    assert not host_has_bs_node(h)


@pytest.mark.parametrize("strategy", ["random", "roundRobin", "leastPing", "leastLoad"])
def test_strategy_defaults(strategy):
    b = HostBalancing(strategy=strategy)
    if strategy == "leastLoad":
        assert b.settings.expected == 2
        assert b.settings.tolerance == 0.1
        assert b.probe.sampling == 3
    elif strategy == "leastPing":
        assert b.probe.interval == "15s"
    else:
        assert b.settings is None and b.probe is None


@pytest.mark.parametrize(
    "payload",
    [
        {"strategy": "unknown"},
        {"strategy": "leastLoad", "settings": {"expected": True}},
        {"strategy": "leastLoad", "settings": {"expected": 1.5}},
        {"strategy": "leastLoad", "settings": {"tolerance": float("nan")}},
        {"strategy": "leastLoad", "settings": {"tolerance": 1.1}},
        {"strategy": "leastLoad", "settings": {"maxRTT": "bad"}},
        {"strategy": "leastLoad", "settings": {"baselines": ["-1s"]}},
        {"strategy": "leastLoad", "settings": {"costs": [{"match": "proxy", "value": 0}]}},
        {"strategy": "leastLoad", "probe": {"interval": "9s"}},
        {"strategy": "leastPing", "probe": {"interval": "0s"}},
        {"strategy": "leastPing", "probe": {"url": "file:///tmp/probe"}},
        {"strategy": "leastPing", "probe": {"sampling": 3}},
        {"strategy": "random", "settings": {"expected": 2}},
        {"strategy": "roundRobin", "probe": {"interval": "15s"}},
        {"strategy": "leastLoad", "unknown": True},
    ],
)
def test_invalid_settings_are_rejected(payload):
    with pytest.raises(ValidationError):
        HostBalancing.model_validate(payload)


def test_special_zero_parameters_and_compound_duration():
    b = HostBalancing(
        strategy="leastLoad", settings={"expected": 0, "maxRTT": "0", "tolerance": 0}, probe={"interval": "1m30s"}
    )
    assert b.settings.maxRTT == "0"


def template():
    return {
        "outbounds": [{"tag": "proxy"}, {"tag": "proxy-1"}, {"tag": "direct"}],
        "routing": {
            "domainStrategy": "AsIs",
            "balancers": [{"tag": "custom", "selector": ["proxy"], "strategy": {"type": "leastLoad"}}],
            "rules": [
                {"type": "field", "domain": ["example.com"], "outboundTag": "direct"},
                {"type": "field", "domain": ["example.net"], "balancerTag": "custom"},
                {"type": "field", "network": "tcp,udp", "outboundTag": "proxy"},
            ],
        },
        "burstObservatory": {"subjectSelector": ["proxy"], "pingConfig": {"interval": "30s"}},
    }


def test_template_balancers_are_preserved_without_host_settings():
    config = template()
    expected = deepcopy(config)
    assert apply_host_balancer(config) == expected


@pytest.mark.parametrize(
    "strategy,observer",
    [("random", None), ("roundRobin", None), ("leastPing", "observatory"), ("leastLoad", "burstObservatory")],
)
def test_managed_balancing_replaces_template_and_retargets_rules(strategy, observer):
    original = template()
    config = deepcopy(original)
    config["observatory"] = {"subjectSelector": ["old"]}
    result = apply_host_balancer(config, HostBalancing(strategy=strategy).model_dump(mode="json"))
    routing = result["routing"]
    assert len(routing["balancers"]) == 1
    assert routing["balancers"][0]["strategy"]["type"] == strategy
    assert routing["rules"][0] == original["routing"]["rules"][0]
    assert routing["rules"][1]["balancerTag"] == "proxy-balancer"
    assert routing["rules"][2]["balancerTag"] == "proxy-balancer"
    assert "outboundTag" not in routing["rules"][2]
    assert len(routing["rules"]) == 3
    assert [k for k in ("observatory", "burstObservatory") if k in result] == ([observer] if observer else [])
    assert apply_host_balancer(deepcopy(result), HostBalancing(strategy=strategy).model_dump(mode="json")) == result
    assert original == template()


def test_managed_leastload_parameters_and_probe():
    settings = HostBalancing(
        strategy="leastLoad",
        settings={"expected": 3, "maxRTT": "2s", "tolerance": 0.2, "baselines": ["200ms"]},
        probe={"url": "https://example.org/probe", "sampling": 5, "timeout": "4s", "interval": "30s"},
    )
    result = apply_host_balancer(template(), settings.model_dump(mode="json"))
    assert result["routing"]["balancers"][0]["strategy"]["settings"]["expected"] == 3
    assert result["burstObservatory"]["pingConfig"]["destination"] == "https://example.org/probe"
    assert result["burstObservatory"]["pingConfig"]["sampling"] == 5


def test_legacy_fallback_preserves_existing_observer():
    config = {
        "routing": {"rules": []},
        "burstObservatory": {"subjectSelector": ["proxy"], "pingConfig": {"interval": "30s"}},
    }
    result = apply_host_balancer(config)
    assert "observatory" not in result
    assert result["burstObservatory"]["pingConfig"]["interval"] == "30s"
    assert result["routing"]["balancers"][0]["strategy"]["type"] == "leastPing"


def test_parameter_errors_preserve_nested_field_paths():
    with pytest.raises(ValidationError) as error:
        HostBalancing.model_validate(
            {"strategy": "leastLoad", "settings": {"expected": -1}, "probe": {"timeout": "bad"}}
        )
    assert {tuple(item["loc"]) for item in error.value.errors()} == {("settings", "expected"), ("probe", "timeout")}
