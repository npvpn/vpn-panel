"""NIC-трафик VPN-нод через Prometheus (как Grafana hosting-nodes-limits / VPN Nodes).

Счётчик node_exporter: sum(increase(rx)) + sum(increase(tx)) по физическим
интерфейсам, без lo/docker/veth/bridge. instance = address:exporter_port.
"""

from __future__ import annotations

import json
import logging
import socket
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, cast
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

LOG = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3), name="MSK")
NIC_DEVICE_RE = r"lo|veth.*|docker.*|br-.*"


def resolve_target_host(address: str, resolve_dns: bool) -> str:
    host = (address or "").strip()
    if not host:
        return ""
    if ":" in host and not host.startswith("["):
        return host
    if not resolve_dns:
        return host
    try:
        socket.inet_aton(host)
    except OSError:
        pass
    else:
        return host
    try:
        return socket.gethostbyname(host)
    except OSError as exc:
        LOG.warning("DNS resolve failed for %s: %s — using hostname", host, exc)
        return host


def instance_for_address(address: str, exporter_port: int, resolve_dns: bool) -> str:
    host = resolve_target_host(address, resolve_dns=resolve_dns)
    if not host:
        return ""
    return host if (":" in host and not host.startswith("[")) else f"{host}:{exporter_port}"


def promql_duration(start: datetime, end: datetime, min_seconds: int = 60) -> str:
    """Prometheus range literal для increase()[RANGE] между start и end."""
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    seconds = max(int((end - start).total_seconds()), min_seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs or not parts:
        parts.append(f"{secs}s")
    return "".join(parts)


def _nic_increase_query(job: str, metric: str, range_literal: str) -> str:
    inst = r'instance=~".*:9100"'
    return f'sum by (instance) (increase({metric}{{job="{job}", {inst}, device!~"{NIC_DEVICE_RE}"}}[{range_literal}]))'


def nic_receive_transmit_queries(job: str, range_literal: str) -> tuple[str, str]:
    rx = _nic_increase_query(job, "node_network_receive_bytes_total", range_literal)
    tx = _nic_increase_query(job, "node_network_transmit_bytes_total", range_literal)
    return rx, tx


def parse_prom_instant_vector(payload: dict) -> dict[str, float]:
    if payload.get("status") != "success":
        raise RuntimeError(str(payload.get("error") or "prometheus error"))
    out: dict[str, float] = {}
    for item in payload.get("data", {}).get("result") or []:
        instance = (item.get("metric") or {}).get("instance")
        raw = (item.get("value") or [None, None])[1]
        if not instance or raw is None:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value != value:
            continue
        out[str(instance)] = value
    return out


def query_prometheus_instant(
    base_url: str,
    query: str,
    eval_time: datetime | None = None,
    timeout: float = 5.0,
) -> dict[str, float]:
    params: dict[str, str] = {"query": query}
    if eval_time is not None:
        ts = eval_time if eval_time.tzinfo else eval_time.replace(tzinfo=UTC)
        params["time"] = str(int(ts.timestamp()))
    url = f"{base_url.rstrip('/')}/api/v1/query?{urlencode(params)}"
    with urlopen(url, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return parse_prom_instant_vector(payload)


def fetch_nic_usage_by_node_id(
    nodes: Sequence[Any],
    start: datetime,
    end: datetime,
    *,
    prometheus_url: str,
    job: str,
    exporter_port: int,
    resolve_dns: bool,
) -> dict[int, tuple[int, int]]:
    """node_id → (receive_bytes, transmit_bytes) за [start, end]."""
    if not prometheus_url.strip():
        return {}

    range_literal = promql_duration(start, end)
    rx_q, tx_q = nic_receive_transmit_queries(job, range_literal)
    eval_time = end if end.tzinfo else end.replace(tzinfo=UTC)

    try:
        rx_by_inst = query_prometheus_instant(prometheus_url, rx_q, eval_time=eval_time)
        tx_by_inst = query_prometheus_instant(prometheus_url, tx_q, eval_time=eval_time)
    except (URLError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
        LOG.warning("[hosting_nic_traffic] prometheus query failed: %s", exc)
        return {}

    instance_to_node: dict[str, int] = {}
    for node in nodes:
        node_id = cast(int | None, node.id)
        address = cast(str | None, node.address)
        if not node_id or not address:
            continue
        inst = instance_for_address(address, exporter_port, resolve_dns)
        if inst:
            instance_to_node[inst] = node_id

    out: dict[int, tuple[int, int]] = {}
    for inst, node_id in instance_to_node.items():
        rx = rx_by_inst.get(inst)
        tx = tx_by_inst.get(inst)
        if rx is None and tx is None:
            continue
        out[node_id] = (int(rx or 0), int(tx or 0))
    return out


def is_calendar_month_to_date_msk(start: datetime, end: datetime, *, slack_seconds: int = 120) -> bool:
    """True, если интервал ≈ с 00:00 MSK 1-го числа текущего месяца до now."""
    now_msk = datetime.now(MSK)
    month_start = now_msk.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    def to_msk(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC).astimezone(MSK)
        return dt.astimezone(MSK)

    start_msk = to_msk(start)
    end_msk = to_msk(end)
    if abs((end_msk - now_msk).total_seconds()) > slack_seconds:
        return False
    return abs((start_msk - month_start).total_seconds()) <= slack_seconds


def fallback_usage_from_db(nodes: Sequence[Any]) -> dict[int, tuple[int, int]]:
    """hosting_used_bytes (rx+tx за MTD) когда Prometheus недоступен."""
    out: dict[int, tuple[int, int]] = {}
    for node in nodes:
        node_id = cast(int | None, node.id)
        used = cast(int | None, node.hosting_used_bytes)
        if node_id is None or used is None:
            continue
        out[node_id] = (0, int(used))
    return out
