"""Скрейп новых метрик читает только in-memory snapshots."""

from __future__ import annotations

import importlib
import importlib.util

from prometheus_client import CollectorRegistry, generate_latest

from tests.test_usage_freshness import state


def test_operation_and_usage_metrics_export_before_first_success():
    assert importlib.util.find_spec("app.utils.operation_metrics"), "Нужен экспорт очередей и freshness"
    module = importlib.import_module("app.utils.operation_metrics")
    runtime = state()
    runtime.observe_nodes({7: "test-node"})
    registry = CollectorRegistry()
    registry.register(
        module.OperationCollector(
            lambda: {
                "active": 4,
                "pending": 161,
                "oldest_pending_seconds": 90,
                "outcomes": {("soft", "coalesced"): 100},
            },
            runtime,
        )
    )
    rendered = generate_latest(registry).decode()
    assert "marzban_node_operations_active 4.0" in rendered
    assert "marzban_node_operations_pending 161.0" in rendered
    assert 'marzban_node_usage_last_success_timestamp_seconds{kind="user",name="test-node"} 0.0' in rendered
    assert 'marzban_node_usage_delay_threshold_seconds{kind="user",name="test-node"} 60.0' in rendered
    assert "coalesced" in rendered
