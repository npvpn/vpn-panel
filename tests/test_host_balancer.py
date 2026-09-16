"""Чистые билдеры xray-балансировщика для multi-address хостов (NPVPN-1596)."""

from __future__ import annotations

from app.xray.host_balancer import (
    HOST_BALANCER_TAG,
    apply_host_balancer,
    build_balancer,
    build_balancer_rule,
    build_observatory,
    proxy_outbound_tag,
)


def test_proxy_outbound_tag_first_is_plain_proxy():
    assert proxy_outbound_tag(0) == "proxy"


def test_proxy_outbound_tag_rest_are_suffixed():
    assert proxy_outbound_tag(1) == "proxy-1"
    assert proxy_outbound_tag(2) == "proxy-2"


def test_build_balancer_leastping_over_proxy_prefix():
    bal = build_balancer()
    assert bal["tag"] == HOST_BALANCER_TAG
    assert bal["selector"] == ["proxy"]
    assert bal["strategy"] == {"type": "leastPing"}


def test_build_balancer_rule_is_catch_all_tcp_udp():
    rule = build_balancer_rule()
    assert rule["type"] == "field"
    assert rule["network"] == "tcp,udp"
    assert rule["balancerTag"] == HOST_BALANCER_TAG
    assert "outboundTag" not in rule


def test_build_observatory_probes_proxy_prefix():
    obs = build_observatory()
    assert obs["subjectSelector"] == ["proxy"]
    assert obs["probeUrl"]
    assert obs["probeInterval"]


def test_apply_host_balancer_appends_balancer_and_catch_all_last():
    config = {
        "outbounds": [
            {"tag": "proxy"},
            {"tag": "proxy-1"},
            {"tag": "direct"},
            {"tag": "block"},
        ],
        "routing": {
            "rules": [
                {"type": "field", "domain": ["geosite:category-ads-all"], "outboundTag": "block"},
                {"type": "field", "ip": ["geoip:ru"], "outboundTag": "direct"},
            ],
        },
    }
    result = apply_host_balancer(config)

    # балансировщик добавлен
    assert result["routing"]["balancers"] == [build_balancer()]
    # catch-all — последним, прежние правила сохранены и раньше
    rules = result["routing"]["rules"]
    assert rules[-1] == build_balancer_rule()
    assert rules[0]["outboundTag"] == "block"
    assert rules[1]["outboundTag"] == "direct"
    # observatory на верхнем уровне
    assert result["observatory"] == build_observatory()


def test_apply_host_balancer_handles_missing_routing():
    config = {"outbounds": [{"tag": "proxy"}, {"tag": "proxy-1"}]}
    result = apply_host_balancer(config)
    assert result["routing"]["balancers"] == [build_balancer()]
    assert result["routing"]["rules"] == [build_balancer_rule()]
    assert result["observatory"] == build_observatory()


def test_apply_host_balancer_does_not_mutate_shared_routing():
    # общий routing из карты документов может прийти в несколько конфигов без копии
    shared_routing = {"rules": [{"type": "field", "ip": ["geoip:ru"], "outboundTag": "direct"}]}
    single_cfg = {"outbounds": [{"tag": "proxy"}], "routing": shared_routing}
    bal_cfg_1 = {"outbounds": [{"tag": "proxy"}, {"tag": "proxy-1"}], "routing": shared_routing}
    bal_cfg_2 = {"outbounds": [{"tag": "proxy"}, {"tag": "proxy-1"}], "routing": shared_routing}

    apply_host_balancer(bal_cfg_1)
    apply_host_balancer(bal_cfg_2)

    # общий объект не тронут → одноадресный сервер чист
    assert "balancers" not in shared_routing
    assert shared_routing["rules"] == [{"type": "field", "ip": ["geoip:ru"], "outboundTag": "direct"}]
    assert "balancers" not in single_cfg["routing"]
    assert all(r.get("balancerTag") is None for r in single_cfg["routing"]["rules"])

    # каждый balanced конфиг получил РОВНО ОДИН свой балансировщик
    assert bal_cfg_1["routing"]["balancers"] == [build_balancer()]
    assert bal_cfg_2["routing"]["balancers"] == [build_balancer()]
    assert bal_cfg_1["routing"]["rules"][-1] == build_balancer_rule()


import pytest


def _make_v2ray_json_config():
    """Инстанс V2rayJsonConfig с минимальным шаблоном.

    V2rayJsonConfig.__init__ рендерит mux/user_agent/settings-шаблоны независимо от
    карты документов — если шаблонные зависимости недоступны, тест скипается (как в
    tests/test_subscription_stubs.py::test_build_v2ray_status_stub_v2ray_json_contains_remark).
    """
    template = {
        "remarks": "",
        "outbounds": [
            {"protocol": "freedom", "tag": "direct"},
            {"protocol": "blackhole", "tag": "block"},
        ],
        "routing": {"rules": [{"type": "field", "ip": ["geoip:ru"], "outboundTag": "direct"}]},
    }
    try:
        from app.subscription.v2ray import V2rayJsonConfig

        return V2rayJsonConfig(configs={1: template}, default_id=1)
    except Exception as exc:  # тяжёлые шаблонные зависимости недоступны
        pytest.skip(f"v2ray deps unavailable: {exc}")


def _inbound():
    return {
        "network": "tcp",
        "protocol": "vless",
        "port": 443,
        "tls": "reality",
        "header_type": "",
        "fragment_setting": "",
        "noise_setting": "",
        "path": "",
        "sni": "example.com",
        "host": "",
        "fp": "chrome",
        "pbk": "pbk",
        "sid": "0123",
        "spx": "",
        "alpn": None,
        "ais": "",
    }


def _settings():
    return {"id": "00000000-0000-0000-0000-000000000000", "flow": "xtls-rprx-vision"}


def test_add_single_address_has_no_balancer():
    conf = _make_v2ray_json_config()
    conf.add(remark="Single", address="1.1.1.1", inbound=_inbound(), settings=_settings())
    cfg = conf.config[-1]
    proxy_tags = [o["tag"] for o in cfg["outbounds"] if o["tag"].startswith("proxy")]
    assert proxy_tags == ["proxy"]
    assert "balancers" not in cfg.get("routing", {})
    assert "observatory" not in cfg


def test_add_balanced_builds_n_proxies_balancer_and_observatory():
    conf = _make_v2ray_json_config()
    conf.add_balanced(
        remark="Balance all",
        addresses=["1.1.1.1", "2.2.2.2", "3.3.3.3"],
        inbound=_inbound(),
        settings=_settings(),
    )
    cfg = conf.config[-1]

    proxy_tags = [o["tag"] for o in cfg["outbounds"] if o["tag"].startswith("proxy")]
    assert proxy_tags == ["proxy", "proxy-1", "proxy-2"]
    # адреса разложены по разным outbound
    addrs = [o["settings"]["vnext"][0]["address"] for o in cfg["outbounds"] if o["tag"].startswith("proxy")]
    assert addrs == ["1.1.1.1", "2.2.2.2", "3.3.3.3"]
    # балансировщик + catch-all последним + observatory
    assert cfg["routing"]["balancers"] == [build_balancer()]
    assert cfg["routing"]["rules"][-1] == build_balancer_rule()
    assert cfg["observatory"] == build_observatory()
