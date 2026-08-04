from app.xray.node_config import node_has_inbound


def test_unknown_inbound_tags_allows_any_tag():
    assert node_has_inbound(None, "VLESS_TCP") is True


def test_known_inbound_tags_filters_missing_tag():
    tags = {"VLESS_TCP", "VMESS_WS"}
    assert node_has_inbound(tags, "VLESS_TCP") is True
    assert node_has_inbound(tags, "TROJAN_TCP") is False


def test_empty_inbound_tags_rejects_everything():
    assert node_has_inbound(set(), "VLESS_TCP") is False
