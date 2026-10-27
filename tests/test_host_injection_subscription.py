"""Сквозная сборка самостоятельных endpoints в один клиентский документ."""

import json
from collections import defaultdict
from copy import deepcopy
from types import SimpleNamespace

import pytest

from tests.test_subscription_bs_render import (
    FILE_TEMPLATE,
    BsContext,
    V2rayJsonConfig,
    V2rayShareLink,
    _host,
    _inbound,
    _Protocol,
    _ProxySettings,
    share,
)


def injection(ids=(1, 2), **kw):
    return {
        "injectHosts": [{"selector": {"type": "ids", "values": list(ids)}, "tagPrefix": "proxy", "selectFrom": "ALL"}],
        **kw,
    }


def scenario(
    monkeypatch,
    *,
    directive=None,
    template=None,
    conf=None,
    source_changes=None,
    recipient_changes=None,
    bs=None,
    subset=None,
    tags=None,
):
    a = {
        **_host("same.example", node_ids=[1], remark="AU-1"),
        "id": 1,
        "sni": ["au1.example"],
        "port": 443,
        "is_hidden": True,
        "group_tag": "MAIN",
    }
    b = {
        **_host("same.example", node_ids=[1], remark="AU-2"),
        "id": 2,
        "sni": ["au2.example"],
        "port": 9443,
        "is_hidden": True,
        "group_tag": "MAIN",
    }
    r = {
        **_host("dummy.example", remark="Auto"),
        "id": 3,
        "host_injection": directive or injection(),
        "is_hidden": False,
        "group_tag": "MAIN",
    }
    for i, changes in (source_changes or {}).items():
        (a if i == 1 else b).update(changes)
    r.update(recipient_changes or {})
    inbound_a = _inbound()
    inbound_b = {**_inbound(), "network": "grpc", "path": "/service", "pbk": "other-key"}
    monkeypatch.setattr(
        share.xray, "config", SimpleNamespace(inbounds_by_tag={"tcp": inbound_a, "grpc": inbound_b}), raising=False
    )
    monkeypatch.setattr(share.xray, "hosts", {"tcp": [a, r], "grpc": [b]}, raising=False)
    if conf is None:
        conf = V2rayJsonConfig(configs={1: deepcopy(template or FILE_TEMPLATE)}, default_id=1)
    p = _Protocol()
    output = share.process_inbounds_and_tags(
        {p: tags if tags is not None else ["tcp", "grpc"]},
        {p: _ProxySettings()},
        defaultdict(lambda: "<missing>", BOT_USERNAME="probe-bot"),
        conf,
        bs=bs,
        subset=subset,
    )
    return conf, output


def endpoints(conf):
    return [o for o in conf.config[-1]["outbounds"] if o["protocol"] == "vless"]


def test_mixed_transports_sni_ports_and_same_address(monkeypatch):
    conf, _ = scenario(monkeypatch)
    assert len(conf.config) == 1
    a, b = endpoints(conf)
    assert [a["tag"], b["tag"]] == ["proxy", "proxy-2"]
    assert [a["settings"]["vnext"][0]["port"], b["settings"]["vnext"][0]["port"]] == [443, 9443]
    assert a["streamSettings"]["network"] == "tcp" and b["streamSettings"]["network"] == "grpc"
    assert a["streamSettings"]["realitySettings"]["serverName"] == "au1.example"
    assert b["streamSettings"]["realitySettings"]["serverName"] == "au2.example"
    assert "dummy.example" not in json.dumps(conf.config)


@pytest.mark.parametrize("changes", [{"is_disabled": True}, {"bot_usernames": ["foreign"]}])
def test_unavailable_source_is_not_injected(monkeypatch, changes):
    conf, _ = scenario(monkeypatch, source_changes={2: changes})
    assert len(endpoints(conf)) == 1


def test_bs_source_excluded_and_all_blocked_stub(monkeypatch):
    bs = BsContext(frozenset({1}), "BS limit")
    conf, _ = scenario(monkeypatch, bs=bs, source_changes={2: {"node_ids": [2]}})
    assert (
        len(endpoints(conf)) == 1
        and endpoints(conf)[0]["streamSettings"]["realitySettings"]["serverName"] == "au2.example"
    )
    conf, _ = scenario(monkeypatch, bs=bs)
    assert len(conf.config) == 1 and conf.config[0]["remarks"] == "BS limit"
    assert "same.example" not in json.dumps(conf.config)


def test_non_json_omits_composite_and_hidden(monkeypatch):
    conf, result = scenario(monkeypatch, conf=V2rayShareLink())
    assert result == []


def test_json_directive_removed_and_form_override(monkeypatch):
    template = {**deepcopy(FILE_TEMPLATE), "remnawave": injection((2,))}
    before = deepcopy(template)
    conf, _ = scenario(
        monkeypatch,
        template=template,
        recipient_changes={"host_injection": None},
        source_changes={1: {"host_injection": {"enabled": False}}, 2: {"host_injection": {"enabled": False}}},
    )
    assert len(endpoints(conf)) == 1
    assert "remnawave" not in conf.config[-1] and template == before
    conf, _ = scenario(
        monkeypatch,
        template=template,
        source_changes={1: {"host_injection": {"enabled": False}}, 2: {"host_injection": {"enabled": False}}},
    )
    assert len(endpoints(conf)) == 2


def test_groups_and_fallback_retarget_proxy_and_observe_backup(monkeypatch):
    directive = injection((1,))
    directive["injectHosts"].append(
        {"selector": {"type": "ids", "values": [2]}, "tagPrefix": "backup", "selectFrom": "ALL"}
    )
    template = deepcopy(FILE_TEMPLATE)
    template["routing"] = {"rules": [{"type": "field", "network": "tcp,udp", "outboundTag": "proxy"}]}
    template["observatory"] = {"subjectSelector": ["proxy"]}
    conf, _ = scenario(monkeypatch, directive=directive, template=template)
    assert conf.config[-1]["observatory"]["subjectSelector"] == ["proxy", "backup"]
    assert conf.config[-1]["routing"]["rules"][0]["balancerTag"] == "proxy-balancer"


def test_source_helpers_are_separate_and_not_balanced(monkeypatch):
    conf, _ = scenario(
        monkeypatch, source_changes={1: {"fragment_setting": "10-20,1-2,tlshello"}, 2: {"noise_setting": "rand:1-2"}}
    )
    proxy = endpoints(conf)
    helper_tags = [o["streamSettings"]["sockopt"]["dialerProxy"] for o in proxy]
    assert len(set(helper_tags)) == 2
    all_tags = {o["tag"] for o in conf.config[-1]["outbounds"]}
    assert set(helper_tags) <= all_tags
    assert not any(t.startswith("proxy") for t in helper_tags)


def test_collision_and_empty_do_not_fall_back_to_recipient(monkeypatch):
    directive = injection()
    directive["injectHosts"][0]["tagPrefix"] = "direct"
    conf, _ = scenario(monkeypatch, directive=directive)
    assert conf.config == []
    conf, _ = scenario(monkeypatch, directive=injection((999,)))
    assert conf.config == []


def test_own_endpoint_optin_and_self_selection_are_distinct(monkeypatch):
    conf, _ = scenario(monkeypatch, directive=injection((3, 1), addVirtualHostAsOutbound=True))
    assert [o["tag"] for o in endpoints(conf)] == ["proxy", "proxy-2"]
    assert endpoints(conf)[0]["settings"]["vnext"][0]["address"] == "dummy.example"


def test_effective_inbounds_are_checked_for_source_and_recipient(monkeypatch):
    conf, _ = scenario(monkeypatch, tags=["tcp"])
    assert len(endpoints(conf)) == 1
    conf, _ = scenario(monkeypatch, tags=["grpc"])
    assert conf.config == []


def test_pins_match_direct_source_and_injected_source_and_do_not_leak(monkeypatch):
    from app.subscription.address_context import AddressContext

    changes = {1: {"is_hidden": False, "address": ["a.example", "b.example"], "node_ids": [1, 2]}}
    conf, _ = scenario(monkeypatch, source_changes=changes, subset=AddressContext(user_id=1, pins={1: [2]}))
    direct, composite = conf.config
    assert direct["outbounds"][0]["settings"]["vnext"][0]["address"] == "b.example"
    assert endpoints(conf)[0]["settings"]["vnext"][0]["address"] == "b.example"
    next_user, _ = scenario(monkeypatch, source_changes=changes, subset=AddressContext(user_id=2, pins={1: [1]}))
    assert endpoints(next_user)[0]["settings"]["vnext"][0]["address"] == "a.example"


def test_recipient_pins_are_ignored_for_optin_own_endpoints(monkeypatch):
    from app.subscription.address_context import AddressContext

    conf, _ = scenario(
        monkeypatch,
        directive=injection((1,), addVirtualHostAsOutbound=True),
        recipient_changes={"address": ["r1.example", "r2.example"], "node_ids": [1, 2]},
        subset=AddressContext(user_id=1, pins={3: [2]}),
    )
    assert [o["settings"]["vnext"][0]["address"] for o in endpoints(conf)] == [
        "r1.example",
        "r2.example",
        "same.example",
    ]


def test_virtual_sources_are_not_recursed_and_native_optin_is_allowed(monkeypatch):
    conf, _ = scenario(monkeypatch, source_changes={2: {"host_injection": injection((1,))}})
    assert len(endpoints(conf)) == 1
    conf, _ = scenario(
        monkeypatch, source_changes={2: {"host_injection": injection((3,), addVirtualHostAsOutbound=True)}}
    )
    assert len(endpoints(conf)) == 2


def test_inherited_manual_balancers_and_observers_survive_composition(monkeypatch):
    template = deepcopy(FILE_TEMPLATE)
    template["routing"] = {
        "balancers": [{"tag": "manual", "selector": ["proxy"], "strategy": {"type": "random"}}],
        "rules": [{"type": "field", "network": "tcp", "balancerTag": "manual"}],
    }
    template["observatory"] = {"subjectSelector": ["proxy"], "probeInterval": "41s"}
    conf, _ = scenario(monkeypatch, template=template)
    assert conf.config[-1]["routing"] == template["routing"]
    assert conf.config[-1]["observatory"] == template["observatory"]


@pytest.mark.parametrize("allow_trojan", [True, False])
def test_distinct_protocols_use_current_user_credentials(monkeypatch, allow_trojan):
    from app.subscription.host_candidates import compose_endpoints, prepare_candidates

    vless = _Protocol()

    # A hashable protocol key, like the production enum.
    class Trojan:
        name = "trojan"

    trojan = Trojan()
    receiver = {**_host("virtual.invalid"), "id": 3, "host_injection": injection()}
    source1 = {**_host("one.example"), "id": 1}
    source2 = {**_host("two.example"), "id": 2}
    for user_id in ("first-user", "second-user"):

        class Password:
            def model_dump(self):
                return {"password": user_id}

        candidates = prepare_candidates(
            {vless: ["tcp"], trojan: ["grpc"]},
            {vless: _ProxySettings(), **({trojan: Password()} if allow_trojan else {})},
            defaultdict(str, BOT_USERNAME="probe-bot"),
            inbounds_by_tag={
                "tcp": _inbound(),
                "grpc": {**_inbound(), "protocol": "trojan", "network": "grpc", "tls": "tls"},
            },
            hosts_by_tag={"tcp": [source1, receiver], "grpc": [source2]},
            is_json=True,
            template_for=lambda h: FILE_TEMPLATE,
        )
        selected, _, _ = compose_endpoints(next(c for c in candidates if c["host"]["id"] == 3), candidates)
        conf = V2rayJsonConfig(configs={1: deepcopy(FILE_TEMPLATE)}, default_id=1)
        conf.add_composed("mixed", selected)
        out = conf.config[0]["outbounds"]
        assert out[0]["settings"]["vnext"][0]["users"][0]["id"] == _ProxySettings().model_dump()["id"]
        if not allow_trojan:
            assert all(o["protocol"] != "trojan" for o in out)
            continue
        assert out[1]["settings"]["servers"][0]["password"] == user_id
        assert out[1]["protocol"] == "trojan"


@pytest.mark.parametrize("kind", ["route", "balancer", "fallback", "selector", "dialer", "proxy"])
def test_invalid_final_tag_graph_omits_only_composite(monkeypatch, kind):
    template = deepcopy(FILE_TEMPLATE)
    template["routing"] = {
        "rules": [],
        "balancers": [{"tag": "manual", "selector": ["proxy"], "strategy": {"type": "random"}}],
    }
    if kind == "route":
        template["routing"]["rules"].append({"type": "field", "network": "tcp", "outboundTag": "missing"})
    elif kind == "balancer":
        template["routing"]["rules"].append({"type": "field", "network": "tcp", "balancerTag": "missing"})
    elif kind == "fallback":
        template["routing"]["balancers"][0]["fallbackTag"] = "missing"
    elif kind == "selector":
        template["routing"]["balancers"][0]["selector"] = ["missing"]
    elif kind == "dialer":
        template["outbounds"][0]["streamSettings"] = {"sockopt": {"dialerProxy": "missing"}}
    else:
        template["outbounds"][0]["proxySettings"] = {"tag": "missing"}
    conf, _ = scenario(monkeypatch, template=template, source_changes={1: {"is_hidden": False}})
    # Ordinary source remains compatible; a broken composed document is not emitted.
    assert len(conf.config) == 1 and conf.config[0]["remarks"] == "AU-1"
