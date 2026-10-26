"""Суточные NIC-снимки и агрегация для /nodes/usage."""

from __future__ import annotations

import sys
import types
from datetime import UTC, date, datetime, timedelta, timezone

_saved_stubs: dict[str, types.ModuleType] = {}
for _name, _module in list(sys.modules.items()):
    if _name.startswith("app.") and not hasattr(_module, "__file__") and not hasattr(_module, "__path__"):
        _saved_stubs[_name] = sys.modules.pop(_name)

_share_stub = types.ModuleType("app.subscription.share")
_share_stub.generate_v2ray_links = lambda *args, **kwargs: []
sys.modules.setdefault("app.subscription.share", _share_stub)

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.crud import get_nodes_usage  # noqa: E402
from app.db.models import Node, NodeHostingNicDaily, NodeUsage  # noqa: E402
from app.models.node import NodeStatus  # noqa: E402
from app.utils import hosting_nic_traffic as nic  # noqa: E402

if sys.modules.get("app.subscription.share") is _share_stub:
    del sys.modules["app.subscription.share"]

sys.modules.update(_saved_stubs)

MSK = timezone(timedelta(hours=3))


def _sqlite_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_nic_usage_from_daily_sums_days_in_range():
    db = _sqlite_session()
    node = Node(name="n1", address="1.1.1.1", port=62050, api_port=62051, status=NodeStatus.connected)
    db.add(node)
    db.commit()
    db.add(NodeHostingNicDaily(node_id=node.id, day=date(2026, 3, 10), used_bytes=100))
    db.add(NodeHostingNicDaily(node_id=node.id, day=date(2026, 3, 11), used_bytes=200))
    db.add(NodeHostingNicDaily(node_id=node.id, day=date(2026, 3, 20), used_bytes=999))
    db.commit()

    start = datetime(2026, 3, 10, 12, 0, tzinfo=MSK)
    end = datetime(2026, 3, 11, 18, 0, tzinfo=MSK)
    got = nic.nic_usage_from_daily(db, start, end)
    assert got[node.id] == (0, 300)
    db.close()


def test_get_nodes_usage_overwrites_with_daily_nic():
    db = _sqlite_session()
    node = Node(
        name="host-node",
        address="203.0.113.1",
        port=62050,
        api_port=62051,
        status=NodeStatus.connected,
        hosting_used_bytes=99_000_000,
    )
    db.add(node)
    db.commit()
    db.add(NodeHostingNicDaily(node_id=node.id, day=date(2026, 3, 1), used_bytes=4000))
    db.add(NodeHostingNicDaily(node_id=node.id, day=date(2026, 3, 2), used_bytes=8000))
    hour = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    db.add(NodeUsage(created_at=hour, node_id=node.id, uplink=100, downlink=200))
    db.commit()

    start = datetime(2026, 3, 1, tzinfo=MSK)
    end = datetime(2026, 3, 2, 23, 59, tzinfo=MSK)
    rows, source = get_nodes_usage(db, start, end)
    assert source == "nic"
    by_name = {r.node_name: r for r in rows}
    assert by_name["host-node"].downlink == 12000
    assert by_name["host-node"].uplink == 0
    db.close()


def test_get_nodes_usage_keeps_xray_without_nic_pipeline():
    """Отдельная панель: нет daily и устаревший hosting — показываем node_usages."""
    db = _sqlite_session()
    node = Node(
        name="solo",
        address="203.0.113.2",
        port=62050,
        api_port=62051,
        status=NodeStatus.connected,
        hosting_used_bytes=50_000_000,
        hosting_used_at=datetime(2020, 1, 1, tzinfo=UTC),
    )
    db.add(node)
    db.commit()
    hour = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    db.add(NodeUsage(created_at=hour, node_id=node.id, uplink=11, downlink=22))
    db.commit()

    now_msk = datetime.now(MSK)
    start = now_msk.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    rows, source = get_nodes_usage(db, start, now_msk)
    assert source == "panel"
    by_name = {r.node_name: r for r in rows}
    assert by_name["solo"].uplink == 11
    assert by_name["solo"].downlink == 22
    db.close()


def test_daily_usage_includes_only_active_adjustments_in_range():
    """Поправки складываются с raw NIC один раз, отмена и соседняя нода изолированы."""
    from app.db.models import NodeHostingTrafficAdjustment

    db = _sqlite_session()
    node = Node(name="corrected", address="203.0.113.1", port=62050, api_port=62051, status=NodeStatus.connected)
    other = Node(name="other", address="203.0.113.2", port=62050, api_port=62051, status=NodeStatus.connected)
    db.add_all([node, other])
    db.commit()
    day = date(2026, 10, 26)
    db.add_all(
        [
            NodeHostingNicDaily(node_id=node.id, day=day, used_bytes=100),
            NodeHostingNicDaily(node_id=other.id, day=day, used_bytes=200),
        ]
    )
    for ident, node_id, delta, at, cancelled in [
        ("active", node.id, 40, datetime(2026, 10, 26, 10), None),
        ("cancelled", node.id, 500, datetime(2026, 10, 26, 10), datetime(2026, 10, 26, 11)),
        ("old", node.id, 900, datetime(2026, 9, 26, 10), None),
        ("other", other.id, -10, datetime(2026, 10, 26, 10), None),
    ]:
        db.add(
            NodeHostingTrafficAdjustment(
                id=ident,
                node_id=node_id,
                delta_bytes=delta,
                raw_bytes=100,
                actual_bytes=140,
                reason="provider total",
                created_at=at,
                cancelled_at=cancelled,
            )
        )
    db.commit()
    got = nic.nic_usage_from_daily(db, datetime(2026, 10, 26, tzinfo=MSK), datetime(2026, 10, 26, 23, tzinfo=MSK))
    assert got == {node.id: (0, 140), other.id: (0, 190)}
    db.close()


def test_adjustment_migration_round_trip_and_cascade():
    """Миграция хранит большие signed bytes и не оставляет записей удалённой ноды."""
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect, text

    migration = (
        Path(__file__).resolve().parents[1]
        / "app/db/migrations/versions/70907486dd1d_node_hosting_traffic_adjustments.py"
    )
    spec = importlib.util.spec_from_file_location("traffic_adjustments_migration", migration)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        connection.execute(text("CREATE TABLE nodes (id INTEGER PRIMARY KEY)"))
        operations = Operations(MigrationContext.configure(connection))
        original_op = module.op
        module.op = operations
        try:
            module.upgrade()
            connection.execute(text("INSERT INTO nodes VALUES (17)"))
            connection.execute(
                text(
                    "INSERT INTO node_hosting_traffic_adjustments "
                    "(id,node_id,raw_bytes,actual_bytes,delta_bytes,reason,created_at) "
                    "VALUES ('one',17,5000000000000,100,-4999999999900,'test','2026-10-26 12:00:00')"
                )
            )
            assert (
                connection.execute(text("SELECT delta_bytes FROM node_hosting_traffic_adjustments")).scalar_one()
                == -4999999999900
            )
            connection.execute(text("DELETE FROM nodes WHERE id=17"))
            assert connection.execute(text("SELECT COUNT(*) FROM node_hosting_traffic_adjustments")).scalar_one() == 0
            module.downgrade()
            assert "node_hosting_traffic_adjustments" not in inspect(connection).get_table_names()
        finally:
            module.op = original_op
