import types

from app.models.node import NodeStatus
from app.xray.host_addresses import (
    bot_has_bs_hosts,
    host_has_bs_node,
    resolve_host_addresses,
    resolve_host_node_ids,
)


def _node(address, status, node_id=0, is_bs=False):
    return types.SimpleNamespace(id=node_id, address=address, status=status, is_bs=is_bs)


def _host(address, nodes):
    return types.SimpleNamespace(address=address, nodes=nodes)


def test_static_address_takes_priority_over_nodes():
    host = _host(
        "1.2.3.4, 5.6.7.8",
        [_node("9.9.9.9", NodeStatus.connected)],
    )
    assert resolve_host_addresses(host) == ["1.2.3.4", "5.6.7.8"]


def test_empty_address_collects_active_nodes_excluding_disabled():
    host = _host(
        "",
        [
            _node("10.0.0.1", NodeStatus.connected),
            _node("10.0.0.2", NodeStatus.disabled),
        ],
    )
    assert resolve_host_addresses(host) == ["10.0.0.1"]


def test_node_returns_from_disabled_reappears():
    node = _node("10.0.0.2", NodeStatus.disabled)
    host = _host("", [_node("10.0.0.1", NodeStatus.connected), node])
    assert resolve_host_addresses(host) == ["10.0.0.1"]
    node.status = NodeStatus.connecting
    assert resolve_host_addresses(host) == ["10.0.0.1", "10.0.0.2"]


def test_empty_address_no_nodes_returns_empty():
    assert resolve_host_addresses(_host("", [])) == []


# --- resolve_host_node_ids: множество нод должно совпадать с тем, по которому строятся адреса ---


def test_node_ids_with_static_address_include_disabled_nodes():
    """Хост со статическим адресом (домен) отдаётся клиенту всегда, значит за ним стоят
    ВСЕ привязанные ноды, включая disabled: иначе юзер с исчерпанным БС-лимитом получил
    бы рабочий БС-хост (обход лимита)."""
    host = _host(
        "bs.example.com",
        [
            _node("10.0.0.1", NodeStatus.connected, node_id=1),
            _node("10.0.0.2", NodeStatus.disabled, node_id=2),
        ],
    )
    assert resolve_host_node_ids(host) == [1, 2]


def test_node_ids_without_address_exclude_disabled_nodes():
    """Адрес хоста собирается от нод — disabled-ноды в подписку не попадают, значит и
    БС-признак/БС-блокировку они давать не должны (иначе хост с живой обычной нодой
    превратился бы в мёртвую заглушку из-за лимита на выключенной БС-ноде)."""
    host = _host(
        "",
        [
            _node("10.0.0.1", NodeStatus.connected, node_id=1),
            _node("10.0.0.2", NodeStatus.disabled, node_id=2),
        ],
    )
    assert resolve_host_addresses(host) == ["10.0.0.1"]
    assert resolve_host_node_ids(host) == [1]


def test_node_ids_and_addresses_are_built_from_the_same_nodes():
    """Явная проверка инварианта: сколько адресов от нод — столько же и node_ids."""
    nodes = [
        _node("10.0.0.1", NodeStatus.connected, node_id=1),
        _node("10.0.0.2", NodeStatus.disabled, node_id=2),
        _node("10.0.0.3", NodeStatus.connecting, node_id=3),
    ]
    host = _host("", nodes)
    addresses = resolve_host_addresses(host)
    node_ids = resolve_host_node_ids(host)
    assert len(addresses) == len(node_ids)
    assert [node.address for node in nodes if node.id in node_ids] == addresses


def test_node_ids_empty_without_nodes():
    assert resolve_host_node_ids(_host("bs.example.com", [])) == []
    assert resolve_host_node_ids(_host("", [])) == []


def test_host_has_bs_node_when_any_visible_node_is_bs():
    host = _host(
        "",
        [
            _node("10.0.0.1", NodeStatus.connected, node_id=1, is_bs=False),
            _node("10.0.0.2", NodeStatus.connected, node_id=2, is_bs=True),
        ],
    )
    assert host_has_bs_node(host) is True


def test_host_has_bs_node_false_without_bs_nodes():
    host = _host("", [_node("10.0.0.1", NodeStatus.connected, node_id=1)])
    assert host_has_bs_node(host) is False


def test_host_has_bs_node_static_address_counts_disabled_bs_node():
    host = _host("bs.example.com", [_node("10.0.0.2", NodeStatus.disabled, node_id=2, is_bs=True)])
    assert host_has_bs_node(host) is True


def test_host_has_bs_node_ignores_disabled_bs_node_when_addresses_come_from_nodes():
    host = _host("", [_node("10.0.0.2", NodeStatus.disabled, node_id=2, is_bs=True)])
    assert host_has_bs_node(host) is False


def _cached_host(*, is_bs, bot_usernames):
    return {"is_bs": is_bs, "bot_usernames": bot_usernames}


def test_bot_has_bs_hosts_for_own_bot():
    hosts = {"vless": [_cached_host(is_bs=True, bot_usernames=["bot_a"])]}
    assert bot_has_bs_hosts(hosts, "bot_a") is True
    assert bot_has_bs_hosts(hosts, "bot_b") is False


def test_bot_has_bs_hosts_unrestricted_host_counts_for_every_bot():
    hosts = {"vless": [_cached_host(is_bs=True, bot_usernames=[])]}
    assert bot_has_bs_hosts(hosts, "bot_a") is True
    assert bot_has_bs_hosts(hosts, "bot_b") is True


def test_bot_has_bs_hosts_ignores_plain_hosts():
    hosts = {"vless": [_cached_host(is_bs=False, bot_usernames=["bot_a"])]}
    assert bot_has_bs_hosts(hosts, "bot_a") is False
