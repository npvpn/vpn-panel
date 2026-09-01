"""Лимит трафика хостера на ноду: ТБ→байты, CRUD, очистка null."""

from __future__ import annotations

import sys
import types
from datetime import datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

for _name, _module in list(sys.modules.items()):
    if _name.startswith("app.") and not hasattr(_module, "__file__") and not hasattr(_module, "__path__"):
        del sys.modules[_name]

_share_stub = types.ModuleType("app.subscription.share")
_share_stub.generate_v2ray_links = lambda *args, **kwargs: []
sys.modules.setdefault("app.subscription.share", _share_stub)

from app.db.base import Base  # noqa: E402
from app.db.crud import create_node, update_node  # noqa: E402
from app.db.models import Node  # noqa: E402
from app.models.node import (  # noqa: E402
    NodeCreate,
    NodeModify,
    hosting_tb_to_bytes,
)

if sys.modules.get("app.subscription.share") is _share_stub:
    del sys.modules["app.subscription.share"]


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_model_declares_nullable_bigint_limit():
    column = Node.__table__.c.hosting_traffic_limit_bytes
    assert isinstance(column.type, BigInteger)
    assert column.nullable is True


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0.7, 700_000_000_000),
        ("0,7", 700_000_000_000),
        ("0.7", 700_000_000_000),
        (" 1 ", 1_000_000_000_000),
        ("", None),
        (None, None),
    ],
)
def test_tb_to_bytes(raw, expected):
    assert hosting_tb_to_bytes(raw) == expected


def test_tb_to_bytes_rejects_non_positive():
    with pytest.raises(ValueError):
        hosting_tb_to_bytes(0)
    with pytest.raises(ValueError):
        hosting_tb_to_bytes("-1")


def test_node_create_rejects_zero_limit():
    with pytest.raises(ValidationError):
        NodeCreate(name="de-1", address="1.2.3.4", hosting_traffic_limit_bytes=0)


def test_create_node_stores_limit(db):
    created = create_node(
        db,
        NodeCreate(name="de-1", address="1.2.3.4", hosting_traffic_limit_bytes=700_000_000_000),
    )
    stored = db.query(Node).filter(Node.id == created.id).one()
    assert stored.hosting_traffic_limit_bytes == 700_000_000_000


def test_create_node_limit_defaults_to_null(db):
    created = create_node(db, NodeCreate(name="nl-1", address="10.0.0.1"))
    assert db.query(Node).filter(Node.id == created.id).one().hosting_traffic_limit_bytes is None


def test_update_node_sets_and_clears_limit(db):
    node = Node(
        name="nl-2",
        address="10.0.0.2",
        port=62050,
        api_port=62051,
        created_at=datetime.utcnow(),
        hosting_traffic_limit_bytes=1_000_000_000_000,
    )
    db.add(node)
    db.commit()
    db.refresh(node)

    updated = update_node(db, node, NodeModify(hosting_traffic_limit_bytes=2_000_000_000_000))
    assert updated.hosting_traffic_limit_bytes == 2_000_000_000_000

    cleared = update_node(db, updated, NodeModify(hosting_traffic_limit_bytes=None))
    assert cleared.hosting_traffic_limit_bytes is None


def test_update_node_omitted_limit_keeps_previous(db):
    node = Node(
        name="nl-3",
        address="10.0.0.3",
        port=62050,
        api_port=62051,
        created_at=datetime.utcnow(),
        hosting_traffic_limit_bytes=500_000_000_000,
    )
    db.add(node)
    db.commit()
    db.refresh(node)

    update_node(db, node, NodeModify(name="nl-3-renamed"))
    assert db.query(Node).filter(Node.id == node.id).one().hosting_traffic_limit_bytes == 500_000_000_000
