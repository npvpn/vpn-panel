"""Поле routing_profile_id ноды: CRUD-прокидывание из NodeCreate/NodeModify (NPVPN-2024).

Валидация значения (существует ли профиль) — в тестах сервиса
`tests/test_xray_templates_service.py::test_assert_profile_exists_*`. Здесь — только то, что
сервисный слой crud (app/db/crud.py) действительно записывает и обновляет значение колонки:
модели ноды в Task 4 получили поле, но без прокидывания в crud.create_node/update_node оно
осело бы в API-запросе и никогда не попало бы в БД.
"""

from __future__ import annotations

import sys
import types
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
from app.db.crud import create_node, update_node  # noqa: E402
from app.db.models import Node  # noqa: E402
from app.models.node import NodeCreate, NodeModify  # noqa: E402

if sys.modules.get("app.subscription.share") is _share_stub:
    del sys.modules["app.subscription.share"]


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_create_node_stores_routing_profile_id(db):
    created = create_node(db, NodeCreate(name="de-1", address="1.2.3.4", routing_profile_id=7))
    assert db.query(Node).filter(Node.id == created.id).one().routing_profile_id == 7


def test_create_node_profile_defaults_to_null(db):
    created = create_node(db, NodeCreate(name="nl-1", address="10.0.0.1"))
    assert db.query(Node).filter(Node.id == created.id).one().routing_profile_id is None


def test_update_node_sets_and_clears_routing_profile_id(db):
    node = Node(
        name="nl-2",
        address="10.0.0.2",
        port=62050,
        api_port=62051,
        created_at=datetime.utcnow(),
        routing_profile_id=3,
    )
    db.add(node)
    db.commit()
    db.refresh(node)

    updated = update_node(db, node, NodeModify(routing_profile_id=9))
    assert updated.routing_profile_id == 9

    cleared = update_node(db, updated, NodeModify(routing_profile_id=None))
    assert cleared.routing_profile_id is None


def test_update_node_omitted_routing_profile_id_keeps_previous(db):
    node = Node(
        name="nl-3",
        address="10.0.0.3",
        port=62050,
        api_port=62051,
        created_at=datetime.utcnow(),
        routing_profile_id=5,
    )
    db.add(node)
    db.commit()
    db.refresh(node)

    update_node(db, node, NodeModify(name="nl-3-renamed"))
    assert db.query(Node).filter(Node.id == node.id).one().routing_profile_id == 5
