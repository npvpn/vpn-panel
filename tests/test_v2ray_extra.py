"""xhttp/splithttp: extra сериализуется компактно, без пробелов.

Регрессия NPVPN-1583: пробелы в JSON extra кодировались urlencode как "+",
клиенты (Happ на iOS) не декодировали "+" обратно в пробел и ломали extra.
"""

from __future__ import annotations

import base64  # noqa: E402
import json
import sys
import types
from urllib.parse import parse_qs

# v2ray.py на импорте тянет тяжёлые модули (шаблоны, config, xray),
# которые не нужны для проверки сериализации xhttp-ссылок. Заглушаем их.
# Значения — заглушки-константы: в тестируемом пути (xhttp) они не вызываются.
for _name, _attrs in {
    "app.subscription.funcs": {"get_grpc_gun": None, "get_grpc_multi": None},
    "app.templates": {"render_template": None},
    "app.utils.helpers": {"UUIDEncoder": json.JSONEncoder},
    "app.xray.client_configs": {
        "select_config": None,
        "parse_json_object": None,
    },
}.items():
    if _name not in sys.modules:
        _mod = types.ModuleType(_name)
        for _k, _v in _attrs.items():
            setattr(_mod, _k, _v)
        sys.modules[_name] = _mod

if "config" not in sys.modules:
    _config = types.ModuleType("config")
    for _const in (
        "EXTERNAL_CONFIG",
        "GRPC_USER_AGENT_TEMPLATE",
        "MUX_TEMPLATE",
        "USER_AGENT_TEMPLATE",
        "V2RAY_SETTINGS_TEMPLATE",
        "V2RAY_SUBSCRIPTION_TEMPLATE",
    ):
        setattr(_config, _const, "")
    sys.modules["config"] = _config

from app.subscription.v2ray import V2rayShareLink  # noqa: E402


def _extra_from_link(link: str) -> str:
    raw_query = link.split("?", 1)[1].split("#", 1)[0]
    return parse_qs(raw_query)["extra"][0]


def test_vless_xhttp_extra_is_compact():
    link = V2rayShareLink.vless(
        remark="test",
        address="example.com",
        port=443,
        id="00000000-0000-0000-0000-000000000000",
        net="xhttp",
        tls="tls",
    )
    raw_query = link.split("?", 1)[1].split("#", 1)[0]
    # После urlencode компактного JSON не должно быть "+" (закодированного пробела)
    assert "+" not in raw_query

    extra = _extra_from_link(link)
    assert " " not in extra
    # extra остаётся валидным JSON
    json.loads(extra)


def test_trojan_xhttp_extra_is_compact():
    link = V2rayShareLink.trojan(
        remark="test",
        address="example.com",
        port=443,
        password="secret",
        net="xhttp",
        tls="tls",
    )
    raw_query = link.split("?", 1)[1].split("#", 1)[0]
    assert "+" not in raw_query

    extra = _extra_from_link(link)
    assert " " not in extra
    json.loads(extra)


def _vmess_payload(link: str) -> dict:
    raw = link[len("vmess://") :]
    return json.loads(base64.b64decode(raw).decode())


def test_vless_xhttp_extra_full_replace():
    custom = {"xPaddingMethod": "tokenish", "seqKey": "chunk_id"}
    link = V2rayShareLink.vless(
        remark="t",
        address="e.com",
        port=443,
        id="00000000-0000-0000-0000-000000000000",
        net="xhttp",
        tls="tls",
        xhttp_extra=custom,
    )
    extra = json.loads(_extra_from_link(link))
    assert extra == custom  # только заданные ключи, без дефолтных 5


def test_trojan_xhttp_extra_full_replace():
    custom = {"xPaddingMethod": "tokenish"}
    link = V2rayShareLink.trojan(
        remark="t",
        address="e.com",
        port=443,
        password="p",
        net="xhttp",
        tls="tls",
        xhttp_extra=custom,
    )
    assert json.loads(_extra_from_link(link)) == custom


def test_vmess_xhttp_extra_full_replace():
    custom = {"xPaddingMethod": "tokenish", "noGRPCHeader": True}
    link = V2rayShareLink.vmess(
        remark="t",
        address="e.com",
        port=443,
        id="00000000-0000-0000-0000-000000000000",
        net="xhttp",
        tls="tls",
        xhttp_extra=custom,
    )
    assert _vmess_payload(link)["extra"] == custom


def test_vless_xhttp_extra_empty_keeps_defaults():
    link = V2rayShareLink.vless(
        remark="t",
        address="e.com",
        port=443,
        id="00000000-0000-0000-0000-000000000000",
        net="xhttp",
        tls="tls",
        xhttp_extra=None,
    )
    extra = json.loads(_extra_from_link(link))
    assert "scMaxEachPostBytes" in extra  # прежняя дефолтная сборка не сломана


from app.subscription.v2ray import V2rayJsonConfig  # noqa: E402


def _splithttp(**kwargs):
    # Обходим тяжёлый __init__: собираем ровно то, что нужно splithttp_config.
    cfg = V2rayJsonConfig.__new__(V2rayJsonConfig)
    cfg.settings = {}
    cfg.user_agent_list = []
    return cfg.splithttp_config(**kwargs)


def test_splithttp_defaults_go_into_nested_extra():
    cfg = _splithttp(path="/p", host="h.com")
    assert "extra" in cfg
    assert cfg["extra"]["scMaxEachPostBytes"] == 1000000
    assert cfg["extra"]["xPaddingBytes"] == "100-1000"
    # ключи больше не лежат в корне splithttpSettings
    assert "scMaxEachPostBytes" not in cfg


def test_splithttp_xhttp_extra_full_replace():
    custom = {"xPaddingMethod": "tokenish", "seqKey": "chunk_id"}
    cfg = _splithttp(path="/p", host="h.com", xhttp_extra=custom)
    assert cfg["extra"] == custom
