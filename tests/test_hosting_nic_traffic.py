"""NIC-трафик нод для /nodes/usage (Prometheus + fallback hosting_used_bytes)."""

from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import patch

from app.utils import hosting_nic_traffic as nic

MSK = timezone(timedelta(hours=3))


def test_promql_duration_min_one_minute():
    start = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    end = start + timedelta(seconds=30)
    assert nic.promql_duration(start, end) in ("60s", "1m")


def test_nic_queries_match_grafana_shape():
    rx, tx = nic.nic_receive_transmit_queries("vpn_nodes", "7d")
    assert 'job="vpn_nodes"' in rx
    assert 'instance=~".*:9100"' in rx
    assert "node_network_receive_bytes_total" in rx
    assert "node_network_transmit_bytes_total" in tx
    assert 'device!~"lo|veth.*|docker.*|br-.*"' in rx


def test_fetch_nic_usage_maps_instance_to_node():
    node = type("N", (), {"id": 5, "name": "nl-1", "address": "203.0.113.10"})()
    rx_payload = {
        "status": "success",
        "data": {"result": [{"metric": {"instance": "203.0.113.10:9100"}, "value": [1, "1000"]}]},
    }
    tx_payload = {
        "status": "success",
        "data": {"result": [{"metric": {"instance": "203.0.113.10:9100"}, "value": [1, "500"]}]},
    }

    def fake_query(_url, query, eval_time=None, timeout=15.0):
        if "receive" in query:
            return nic.parse_prom_instant_vector(rx_payload)
        return nic.parse_prom_instant_vector(tx_payload)

    start = datetime(2026, 3, 1, tzinfo=UTC)
    end = datetime(2026, 3, 8, tzinfo=UTC)
    with patch.object(nic, "query_prometheus_instant", side_effect=fake_query):
        got = nic.fetch_nic_usage_by_node_id(
            [node],
            start,
            end,
            prometheus_url="http://prom:9090",
            job="vpn_nodes",
            exporter_port=9100,
            resolve_dns=False,
        )
    assert got == {5: (1000, 500)}


def test_fallback_usage_from_db_uses_hosting_used_bytes():
    node = type("N", (), {"id": 3, "hosting_used_bytes": 9_000_000})()
    assert nic.fallback_usage_from_db([node]) == {3: (0, 9_000_000)}
