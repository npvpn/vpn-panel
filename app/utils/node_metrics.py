"""Экспортёр состояния нод в Prometheus (NPVPN-1614).

Читает nodes в момент скрейпа — как _DbPoolCollector в db_metrics.py: никаких
фоновых задач и никакой нагрузки между скрейпами. История доступности живёт в
Prometheus (retention 15d), а не в панели — в самой БД лежит только текущий
статус.

Лейбл ровно один — name. Изменчивые поля (status, message, address) в лейблы не
кладём: лейбл входит в идентичность временного ряда, и меняющийся лейбл рвал бы
ряд на куски, ломая avg_over_time.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager

from prometheus_client import REGISTRY
from prometheus_client.core import GaugeMetricFamily

logger = logging.getLogger(__name__)

METRIC_NAME = "marzban_node_up"


class NodeUpCollector:
    """Отдаёт marzban_node_up{name} = 1 для connected, 0 для connecting/error."""

    def __init__(self, session_factory: Callable[[], AbstractContextManager]):
        self._session_factory = session_factory

    def collect(self) -> Iterator[GaugeMetricFamily]:
        try:
            rows = self._read_rows()
        except Exception as exc:
            # Скрейп собирает все коллекторы одним обходом: исключение отсюда
            # уронило бы весь /metrics, а не только метрики нод.
            logger.warning("[metrics] node collector failed: %s", exc)
            return

        gauge = GaugeMetricFamily(
            METRIC_NAME,
            "Node is connected (1) or not (0); disabled nodes are excluded",
            labels=["name"],
        )
        for name, status in rows:
            gauge.add_metric([name], 1.0 if status == "connected" else 0.0)
        yield gauge

    def _read_rows(self) -> list[tuple[str, str]]:
        # Импорт ленивый: модуль не должен тянуть модели и движок на импорте,
        # иначе он неимпортируем в тестовой песочнице (tests/conftest.py).
        from app.db.models import Node
        from app.models.node import NodeStatus

        with self._session_factory() as db:
            rows = db.query(Node.name, Node.status).filter(Node.status != NodeStatus.disabled).all()

        return [(name, getattr(status, "value", status)) for name, status in rows]


_registered = False


def register(session_factory: Callable[[], AbstractContextManager] | None = None) -> None:
    global _registered
    if _registered:
        return
    if session_factory is None:
        from app.db import GetDB

        session_factory = GetDB
    try:
        REGISTRY.register(NodeUpCollector(session_factory))
        _registered = True
    except Exception as exc:
        logger.warning("[metrics] failed to register node collector: %s", exc)
