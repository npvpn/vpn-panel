import json

from app.xray.node_config import (
    build_node_config_json,
    node_signature,
)

# --- FakeConfig: мимикрия XRayConfig (dict + copy(deep) + inbounds_by_tag + to_json) ---
INBOUNDS = [
    {"tag": "API_INBOUND", "protocol": "dokodemo-door"},
    {
        "tag": "VLESS_TCP",
        "protocol": "vless",
        "settings": {
            "clients": [
                {"email": "1.alice", "id": "u1"},
                {"email": "2.bob", "id": "u2"},
            ]
        },
    },
]
MANAGED = {"VLESS_TCP"}


class FakeConfig(dict):
    def __init__(self, *args, inbounds_by_tag=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._inbounds_by_tag = inbounds_by_tag or {}

    @property
    def inbounds_by_tag(self):
        return self._inbounds_by_tag

    def copy(self):
        clone = FakeConfig(inbounds_by_tag=self._inbounds_by_tag)
        clone["inbounds"] = [
            {**i, "settings": {**i.get("settings", {}), "clients": list((i.get("settings") or {}).get("clients", []))}}
            if i.get("settings")
            else dict(i)
            for i in self["inbounds"]
        ]
        clone["outbounds"] = [dict(o) for o in self.get("outbounds", [])]
        return clone

    def to_json(self, **kw):
        return json.dumps({"inbounds": self["inbounds"], "outbounds": self.get("outbounds", [])}, sort_keys=True, **kw)


def _base():
    return FakeConfig(
        {"inbounds": [dict(i) for i in INBOUNDS], "outbounds": [{"tag": "direct"}]},
        inbounds_by_tag={"VLESS_TCP": {}},
    )


def test_signature_is_order_independent():
    a = node_signature(["B", "A"], {"role": "direct"}, [2, 1])
    b = node_signature(["A", "B"], {"role": "direct"}, [1, 2])
    assert a == b


def test_signature_differs_on_cascade():
    direct = node_signature([], {"role": "direct"}, [])
    entry = node_signature([], {"role": "entry", "entry_routes": [{"x": 1}]}, [])
    assert direct != entry


def test_signature_handles_none():
    assert node_signature(None, {"role": "direct"}, None) == ((), json.dumps({"role": "direct"}, sort_keys=True), ())


def test_build_direct_serializes_all_clients():
    js = build_node_config_json(_base(), [], {"role": "direct"}, [])
    data = json.loads(js)
    vless = next(i for i in data["inbounds"] if i["tag"] == "VLESS_TCP")
    assert {c["email"] for c in vless["settings"]["clients"]} == {"1.alice", "2.bob"}


def test_build_strips_blocked_user():
    js = build_node_config_json(_base(), [], {"role": "direct"}, [1])
    data = json.loads(js)
    vless = next(i for i in data["inbounds"] if i["tag"] == "VLESS_TCP")
    assert {c["email"] for c in vless["settings"]["clients"]} == {"2.bob"}


def test_build_filters_inbounds_by_tags():
    # tags=["NOPE"] → остаётся только инфраструктурный API_INBOUND
    js = build_node_config_json(_base(), ["NOPE"], {"role": "direct"}, [])
    data = json.loads(js)
    assert [i["tag"] for i in data["inbounds"]] == ["API_INBOUND"]
