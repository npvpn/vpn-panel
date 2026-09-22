"""crud.get_weight_snapshot: подбор ближайшего снимка, стухание, порядок проверок (NPVPN-2072)."""

from __future__ import annotations

import sys
import types
from datetime import datetime

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

for _name, _module in list(sys.modules.items()):
    if _name.startswith("app.") and not hasattr(_module, "__file__") and not hasattr(_module, "__path__"):
        del sys.modules[_name]

_share_stub = types.ModuleType("app.subscription.share")
_share_stub.generate_v2ray_links = lambda *args, **kwargs: []
sys.modules.setdefault("app.subscription.share", _share_stub)

from app.db.base import Base  # noqa: E402
from app.db.crud import get_weight_snapshot  # noqa: E402
from app.db.models import Node, NodeWeightSnapshot  # noqa: E402

if sys.modules.get("app.subscription.share") is _share_stub:
    del sys.modules["app.subscription.share"]


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _make_node(db, name: str) -> Node:
    node = Node(name=name, address="1.2.3.4", port=62050, api_port=62051, created_at=datetime.utcnow())
    db.add(node)
    db.commit()
    db.refresh(node)
    return node


def test_returns_exact_snapshot(db):
    node = _make_node(db, "nl-1")
    db.add(NodeWeightSnapshot(epoch_index=10, node_id=node.id, weight=500))
    db.commit()

    assert get_weight_snapshot(db, 10) == {node.id: 500.0}


def test_falls_back_to_nearest_earlier_snapshot(db):
    node = _make_node(db, "nl-1")
    db.add(NodeWeightSnapshot(epoch_index=8, node_id=node.id, weight=500))
    db.commit()

    assert get_weight_snapshot(db, 10) == {node.id: 500.0}


def test_ignores_future_snapshot(db):
    node = _make_node(db, "nl-1")
    db.add(NodeWeightSnapshot(epoch_index=12, node_id=node.id, weight=500))
    db.commit()

    assert get_weight_snapshot(db, 10) == {}


def test_stale_snapshot_beyond_two_days_returns_empty(db):
    node = _make_node(db, "nl-1")
    db.add(NodeWeightSnapshot(epoch_index=7, node_id=node.id, weight=500))
    db.commit()

    assert get_weight_snapshot(db, 10) == {}


def test_snapshot_exactly_two_days_old_is_still_valid(db):
    node = _make_node(db, "nl-1")
    db.add(NodeWeightSnapshot(epoch_index=8, node_id=node.id, weight=500))
    db.commit()

    assert get_weight_snapshot(db, 10) == {node.id: 500.0}


def test_no_snapshot_at_all_returns_empty(db):
    assert get_weight_snapshot(db, 10) == {}


def test_stale_snapshot_skips_row_select(db):
    """NPVPN-2072 (MINOR): стухание проверяется до выборки строк — при устаревшем
    снимке лишнего похода в БД за самими весами быть не должно."""
    node = _make_node(db, "nl-1")
    db.add(NodeWeightSnapshot(epoch_index=7, node_id=node.id, weight=500))
    db.commit()

    statements: list[str] = []

    def _record(*args):
        statements.append(str(args[2]))

    event.listen(db.bind, "before_cursor_execute", _record)
    try:
        result = get_weight_snapshot(db, 10)
    finally:
        event.remove(db.bind, "before_cursor_execute", _record)

    assert result == {}
    assert not any("weight" in s.lower() and "select" in s.lower() and "max(" not in s.lower() for s in statements), (
        "запрос строк снимка не должен выполняться, когда снимок уже признан устаревшим"
    )
