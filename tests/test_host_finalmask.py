"""FinalMask на хосте: схема и выдача в Xray JSON (NPVPN-2311)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.proxy import ProxyHost

_FRAGMENT = {
    "tcp": [
        {
            "type": "fragment",
            "settings": {"packets": "tlshello", "length": "1-1", "delay": "0"},
        }
    ]
}


def _host(**overrides) -> ProxyHost:
    data = {"remark": "NL", "address": "1.1.1.1"}
    data.update(overrides)
    return ProxyHost(**data)


def test_finalmask_none_is_accepted():
    assert _host().finalmask is None


def test_fragment_length_and_delay_is_accepted():
    assert _host(finalmask=_FRAGMENT).finalmask == _FRAGMENT


def test_fragment_lengths_and_delays_is_accepted():
    mask = {
        "tcp": [
            {
                "type": "fragment",
                "settings": {"packets": "tlshello", "lengths": ["1-1"], "delays": ["0"]},
            }
        ]
    }
    assert _host(finalmask=mask).finalmask == mask


def test_fragment_interval_is_rejected():
    mask = {
        "tcp": [
            {
                "type": "fragment",
                "settings": {"packets": "tlshello", "length": "1-1", "interval": "0"},
            }
        ]
    }
    with pytest.raises(ValidationError, match="delay"):
        _host(finalmask=mask)


def test_fragment_setting_and_finalmask_together_are_rejected():
    with pytest.raises(ValidationError, match="finalmask"):
        _host(fragment_setting="1-1,0,tlshello", finalmask=_FRAGMENT)


def test_quic_params_object_is_accepted():
    mask = {"quicParams": {}}
    assert _host(finalmask=mask).finalmask == mask


def test_list_and_empty_object_are_rejected():
    with pytest.raises(ValidationError):
        _host(finalmask=[])
    with pytest.raises(ValidationError):
        _host(finalmask={})


def test_unknown_root_key_is_rejected():
    with pytest.raises(ValidationError):
        _host(finalmask={"tcp": _FRAGMENT["tcp"], "extra": 1})


def test_udp_fragment_interval_is_rejected():
    mask = {
        "udp": [
            {
                "type": "fragment",
                "settings": {"packets": "tlshello", "length": "1-1", "interval": "0"},
            }
        ]
    }
    with pytest.raises(ValidationError, match="delay"):
        _host(finalmask=mask)


def test_empty_tcp_layer_is_rejected():
    with pytest.raises(ValidationError):
        _host(finalmask={"tcp": []})


def test_fragment_without_required_settings_is_rejected():
    with pytest.raises(ValidationError):
        _host(finalmask={"tcp": [{"type": "fragment", "settings": {}}]})


def test_quic_params_must_be_an_object():
    with pytest.raises(ValidationError):
        _host(finalmask={"quicParams": []})


def test_finalmask_over_size_limit_is_rejected():
    mask = {"quicParams": {"pad": "x" * 17000}}
    with pytest.raises(ValidationError, match="16384"):
        _host(finalmask=mask)


def _subscription_mask() -> dict:
    return {
        "tcp": [
            {
                "type": "fragment",
                "settings": {"packets": "tlshello", "length": "1-1", "delay": "0"},
            }
        ]
    }


def _make_v2ray_json_config():
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
    except Exception as exc:
        pytest.skip(f"v2ray deps unavailable: {exc}")


def _inbound(**overrides) -> dict:
    inbound = {
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
    inbound.update(overrides)
    return inbound


def _settings() -> dict:
    return {"id": "00000000-0000-0000-0000-000000000000", "flow": "xtls-rprx-vision"}


def _proxy_outbounds(cfg: dict) -> list[dict]:
    return [outbound for outbound in cfg["outbounds"] if str(outbound.get("tag", "")).startswith("proxy")]


def _assert_finalmask_without_fragment_dialer(cfg: dict, mask: dict) -> None:
    proxies = _proxy_outbounds(cfg)
    assert proxies
    for outbound in proxies:
        assert outbound["streamSettings"]["finalmask"] == mask
        assert "dialerProxy" not in (outbound["streamSettings"].get("sockopt") or {})
    for outbound in cfg["outbounds"]:
        assert "fragment" not in (outbound.get("settings") or {})


def test_add_balanced_puts_finalmask_on_each_proxy_without_fragment_dialer():
    mask = _subscription_mask()
    conf = _make_v2ray_json_config()
    conf.add_balanced(
        remark="Balance",
        addresses=["1.1.1.1", "2.2.2.2", "3.3.3.3"],
        inbound=_inbound(finalmask=mask),
        settings=_settings(),
    )
    cfg = conf.config[-1]
    assert [outbound["tag"] for outbound in _proxy_outbounds(cfg)] == ["proxy", "proxy-1", "proxy-2"]
    _assert_finalmask_without_fragment_dialer(cfg, mask)
    assert cfg["routing"]["balancers"][0]["tag"] == "proxy-balancer"
    assert cfg["observatory"]["probeUrl"]


def test_add_puts_finalmask_on_single_proxy():
    mask = _subscription_mask()
    conf = _make_v2ray_json_config()
    conf.add(remark="Single", address="1.1.1.1", inbound=_inbound(finalmask=mask), settings=_settings())
    cfg = conf.config[-1]
    assert [outbound["tag"] for outbound in _proxy_outbounds(cfg)] == ["proxy"]
    _assert_finalmask_without_fragment_dialer(cfg, mask)


def test_finalmask_keeps_noise_dialer_without_fragment():
    mask = _subscription_mask()
    conf = _make_v2ray_json_config()
    conf.add(
        remark="Noise",
        address="1.1.1.1",
        inbound=_inbound(finalmask=mask, noise_setting="rand:10-20,100-200"),
        settings=_settings(),
    )
    cfg = conf.config[-1]
    dialers = [outbound for outbound in cfg["outbounds"] if outbound.get("tag") == "dialer"]
    assert len(dialers) == 1
    assert dialers[0]["settings"]["noises"]
    assert "fragment" not in dialers[0]["settings"]
    assert _proxy_outbounds(cfg)[0]["streamSettings"]["finalmask"] == mask


def test_fragment_setting_without_finalmask_still_builds_dialer():
    conf = _make_v2ray_json_config()
    conf.add(
        remark="Fragment",
        address="1.1.1.1",
        inbound=_inbound(fragment_setting="1-1,0,tlshello"),
        settings=_settings(),
    )
    cfg = conf.config[-1]
    dialers = [outbound for outbound in cfg["outbounds"] if outbound.get("tag") == "dialer"]
    assert dialers[0]["settings"]["fragment"]["interval"] == "0"
    assert "finalmask" not in _proxy_outbounds(cfg)[0]["streamSettings"]


def test_add_copies_finalmask_so_later_mutation_does_not_leak():
    mask = _subscription_mask()
    conf = _make_v2ray_json_config()
    conf.add(remark="Copy", address="1.1.1.1", inbound=_inbound(finalmask=mask), settings=_settings())
    mask["tcp"][0]["settings"]["delay"] = "99"
    stored = _proxy_outbounds(conf.config[-1])[0]["streamSettings"]["finalmask"]
    assert stored["tcp"][0]["settings"]["delay"] == "0"


def test_composed_endpoint_with_finalmask_skips_fragment_dialer():
    from app.subscription.host_candidates import Endpoint

    mask = _subscription_mask()
    conf = _make_v2ray_json_config()
    inbound = _inbound(finalmask=mask, fragment_setting="10-20,10-20,tlshello")
    endpoint = Endpoint(1, "1.1.1.1", inbound, _settings())
    outbounds = conf.build_endpoint_outbounds(endpoint, "proxy", helper_tag="__npvpn_dialer_0")
    proxy = next(outbound for outbound in outbounds if outbound["tag"] == "proxy")
    assert proxy["streamSettings"]["finalmask"] == mask
    assert "dialerProxy" not in (proxy["streamSettings"].get("sockopt") or {})
    assert all("fragment" not in (outbound.get("settings") or {}) for outbound in outbounds)
