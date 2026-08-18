"""Экспорт состояния нод в Prometheus (NPVPN-1614)."""

import sys
import types
from contextlib import contextmanager
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

for _name, _module in list(sys.modules.items()):
    if _name.startswith("app.") and not hasattr(_module, "__file__") and not hasattr(_module, "__path__"):
        del sys.modules[_name]

_share_stub = types.ModuleType("app.subscription.share")
_share_stub.generate_v2ray_links = lambda *args, **kwargs: []
sys.modules.setdefault("app.subscription.share", _share_stub)

from app.db.base import Base  # noqa: E402
from app.db.models import Node  # noqa: E402
from app.models.node import NodeStatus  # noqa: E402
from app.utils.node_metrics import NodeUpCollector  # noqa: E402

if sys.modules.get("app.subscription.share") is _share_stub:
    del sys.modules["app.subscription.share"]


def _node(node_id: int, name: str, status: NodeStatus) -> Node:
    return Node(
        id=node_id,
        name=name,
        address="127.0.0.1",
        port=62050,
        api_port=62051,
        status=status,
        created_at=datetime.utcnow(),
    )


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add(_node(1, "marzban-de-1", NodeStatus.connected))
    session.add(_node(2, "marzban-nl-2", NodeStatus.error))
    session.add(_node(3, "marzban-fr-3", NodeStatus.connecting))
    session.add(_node(4, "marzban-old-4", NodeStatus.disabled))
    session.commit()

    @contextmanager
    def factory():
        yield session

    yield factory
    session.close()


def _samples(collector: NodeUpCollector) -> dict[str, float]:
    return {sample.labels["name"]: sample.value for family in collector.collect() for sample in family.samples}


def test_connected_node_is_up(session_factory):
    assert _samples(NodeUpCollector(session_factory))["marzban-de-1"] == 1.0


def test_error_and_connecting_nodes_are_down(session_factory):
    samples = _samples(NodeUpCollector(session_factory))

    assert samples["marzban-nl-2"] == 0.0
    assert samples["marzban-fr-3"] == 0.0


def test_disabled_node_is_not_exported(session_factory):
    # Админ выключил ноду осознанно: это не авария и не простой, иначе она
    # тянула бы вниз и процент доступности, и суточную статистику.
    assert "marzban-old-4" not in _samples(NodeUpCollector(session_factory))


def test_metric_name_and_labels(session_factory):
    families = list(NodeUpCollector(session_factory).collect())

    assert len(families) == 1
    assert families[0].name == "marzban_node_up"
    assert families[0].samples[0].labels == {"name": "marzban-de-1"}


def test_db_failure_does_not_break_scrape():
    # /metrics собирается одним обходом всех коллекторов: исключение отсюда
    # уронило бы весь эндпоинт, включая метрики пула и HTTP.
    @contextmanager
    def broken_factory():
        raise RuntimeError("db is down")
        yield  # pragma: no cover

    assert list(NodeUpCollector(broken_factory).collect()) == []
