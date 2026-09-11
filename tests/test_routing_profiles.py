from app.xray.routing_profiles import parse_json_object, resolve_routing_profile, select_routing


def host(*node_ids):
    return {"address": ["example.com"], "node_ids": list(node_ids)}


def test_parse_json_object_treats_blank_as_unset():
    assert parse_json_object(None) is None
    assert parse_json_object("   ") is None
    assert parse_json_object('{"a": 1}') == {"a": 1}


def test_parse_json_object_rejects_non_object():
    for raw in ("[1]", '"s"', "{", "3"):
        try:
            parse_json_object(raw)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {raw!r}")


def test_domain_host_on_profiled_node_resolves_profile():
    # Ключевой кейс NPVPN-1652: адрес хоста — домен, нода подключена по IP.
    assert resolve_routing_profile(host(7), {7: 42}) == 42


def test_host_without_nodes_has_no_profile():
    assert resolve_routing_profile(host(), {7: 42}) is None
    assert resolve_routing_profile({"address": ["192.0.2.10"]}, {7: 42}) is None


def test_any_semantics_first_profiled_node_wins():
    assert resolve_routing_profile(host(3, 7), {7: 42}) == 42
    assert resolve_routing_profile(host(3, 4), {7: 42}) is None


def test_empty_profile_map_resolves_nothing():
    assert resolve_routing_profile(host(7), {}) is None


def test_select_routing_falls_back_to_template_routing():
    template = {"rules": ["from-template"]}
    assert select_routing(template, None) == template
    assert select_routing(template, {"rules": ["from-profile"]}) == {"rules": ["from-profile"]}
