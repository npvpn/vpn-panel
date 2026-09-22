"""Лимит трафика хостера на ноду: ТБ→байты, CRUD, очистка null."""

from __future__ import annotations

import sys
import types
from datetime import datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import BigInteger, create_engine, text
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


IEC_TB = 1024**4


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0.7, round(0.7 * IEC_TB)),
        ("0,7", round(0.7 * IEC_TB)),
        ("0.7", round(0.7 * IEC_TB)),
        (" 1 ", IEC_TB),
        ("32", 32 * IEC_TB),
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


def test_hosting_limit_si_to_iec_migration_rescales_stored_bytes():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "app/db/migrations/versions/e8f1a2b3c4d5_hosting_limit_tb_iec.py"
    spec = importlib.util.spec_from_file_location("hosting_limit_iec", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    class _Op:
        def __init__(self, bind):
            self._bind = bind

        def get_bind(self):
            return self._bind

    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE nodes (id INTEGER PRIMARY KEY, hosting_traffic_limit_bytes INTEGER)"))
        conn.execute(
            text(
                "INSERT INTO nodes (id, hosting_traffic_limit_bytes) VALUES "
                "(1, 32000000000000), (2, NULL), (3, 700000000000)"
            )
        )
        orig_op = module.op
        module.op = _Op(conn)
        try:
            module.upgrade()
            rows = {row[0]: row[1] for row in conn.execute(text("SELECT id, hosting_traffic_limit_bytes FROM nodes"))}
            assert rows[1] == 32 * 1024**4
            assert rows[2] is None
            assert rows[3] == round(700_000_000_000 * 1024**4 / 10**12)

            module.downgrade()
            rows = {row[0]: row[1] for row in conn.execute(text("SELECT id, hosting_traffic_limit_bytes FROM nodes"))}
            assert rows[1] == 32_000_000_000_000
            assert rows[3] == 700_000_000_000
        finally:
            module.op = orig_op
