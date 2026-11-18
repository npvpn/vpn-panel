"""Метрики ограниченных очередей и учёта; scrape читает только память."""

from __future__ import annotations

from prometheus_client import REGISTRY
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily

from app.utils.usage_runtime import usage_state


class OperationCollector:
    def __init__(self, operations, usage):
        self.operations = operations
        self.usage = usage

    def collect(self):
        operations = self.operations()
        for key in ("active", "pending", "oldest_pending_seconds"):
            gauge = GaugeMetricFamily(f"marzban_node_operations_{key}", f"Node operations {key}")
            gauge.add_metric([], operations[key])
            yield gauge
        requests = CounterMetricFamily(
            "marzban_node_operation_requests", "Operation admission/result", labels=["kind", "outcome"]
        )
        for labels, count in operations["outcomes"].items():
            requests.add_metric(list(labels), count)
        yield requests
        usage = self.usage.snapshot()
        fields = {
            "last_success_timestamp_seconds": "last_success",
            "tracking_since_timestamp_seconds": "since",
            "accounting_delay_seconds": "delay",
            "delay_threshold_seconds": "threshold",
        }
        for metric, field in fields.items():
            gauge = GaugeMetricFamily(f"marzban_node_usage_{metric}", f"Node usage {field}", labels=["name", "kind"])
            for row in usage["nodes"]:
                gauge.add_metric([row["name"], row["kind"]], row[field])
            yield gauge
        for metric, field, labels in [
            ("errors", "errors", ["kind", "stage"]),
            ("ticks", "ticks", ["kind", "outcome"]),
        ]:
            counter = CounterMetricFamily(f"marzban_usage_{metric}", f"Usage {field}", labels=labels)
            for values, count in usage[field].items():
                counter.add_metric(list(values), count)
            yield counter
        running = GaugeMetricFamily("marzban_usage_ticks_running", "Running usage jobs", labels=["kind"])
        for kind, count in usage["running"].items():
            running.add_metric([kind], count)
        yield running


_registered = False


def _operation_snapshot():
    from app.xray.operations import node_operation_snapshot

    return node_operation_snapshot()


def register():
    global _registered
    if not _registered:
        REGISTRY.register(OperationCollector(_operation_snapshot, usage_state))
        _registered = True
