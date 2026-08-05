from app.xray.node_config import node_has_inbound


def test_unknown_inbound_tags_allows_any_tag():
    assert node_has_inbound(None, "VLESS_TCP") is True


def test_known_inbound_tags_filters_missing_tag():
    tags = {"VLESS_TCP", "VMESS_WS"}
    assert node_has_inbound(tags, "VLESS_TCP") is True
    assert node_has_inbound(tags, "TROJAN_TCP") is False


def test_empty_inbound_tags_allows_everything():
    # Пустой набор == ни одной галочки на ноде в UI. По конвенции
    # apply_inbound_filter это значит «фильтр не применён» — нода реально
    # гоняет xray со всеми инбаундами, поэтому фильтровать вызовы нельзя.
    assert node_has_inbound(set(), "VLESS_TCP") is True
