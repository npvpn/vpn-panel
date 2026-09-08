"""last_seen_at в node_user_usages (NPVPN-1966).

Строка (user, node, hour) живёт весь час, поэтому по created_at нельзя отличить
«сидит сейчас» от «пинганул 55 минут назад». last_seen_at — момент последнего
тика, в котором по этой паре реально шёл трафик.
"""

import sys
import types
from contextlib import contextmanager
from datetime import datetime, timedelta

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
from app.db.models import Node, NodeUserUsage, User  # noqa: E402
from app.jobs import record_usages  # noqa: E402
from app.jobs.record_usages import record_user_stats  # noqa: E402

if sys.modules.get("app.subscription.share") is _share_stub:
    del sys.modules["app.subscription.share"]

NODE_ID = 13
OTHER_NODE_ID = 14
USER_ID = 45581


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Node(id=NODE_ID, name="node-a", address="127.0.0.1", port=62050, api_port=62051))
        session.add(Node(id=OTHER_NODE_ID, name="node-b", address="127.0.0.2", port=62050, api_port=62051))
        session.add(User(id=USER_ID, username="TEST100", created_at=datetime.utcnow()))
        session.commit()
        yield session


@pytest.fixture
def patched_getdb(db, monkeypatch):
    """record_user_stats открывает свою сессию через GetDB — подменяем на тестовую."""

    @contextmanager
    def fake_getdb():
        yield db

    monkeypatch.setattr(record_usages, "GetDB", fake_getdb)


def usage(db, node_id=NODE_ID):
    return db.query(NodeUserUsage).filter(NodeUserUsage.node_id == node_id).one()


def test_insert_sets_last_seen_at(db, patched_getdb):
    before = datetime.utcnow() - timedelta(seconds=1)

    record_user_stats([{"uid": USER_ID, "value": 1024}], NODE_ID)

    row = usage(db)
    assert row.last_seen_at is not None
    assert row.last_seen_at >= before


def test_last_seen_at_is_tick_moment_not_hour_start(db, patched_getdb):
    record_user_stats([{"uid": USER_ID, "value": 1024}], NODE_ID)

    row = usage(db)
    # created_at округлён до начала часа, last_seen_at — нет. Именно это различие
    # и делает панель честной.
    assert row.created_at.minute == 0 and row.created_at.second == 0
    assert row.last_seen_at >= row.created_at


def test_increment_moves_last_seen_at_forward(db, patched_getdb):
    record_user_stats([{"uid": USER_ID, "value": 1024}], NODE_ID)
    first = usage(db).last_seen_at

    db.query(NodeUserUsage).filter(NodeUserUsage.node_id == NODE_ID).update(
        {NodeUserUsage.last_seen_at: first - timedelta(minutes=20)}
    )
    db.commit()

    record_user_stats([{"uid": USER_ID, "value": 2048}], NODE_ID)

    row = usage(db)
    assert row.used_traffic == 3072
    assert row.last_seen_at > first - timedelta(minutes=20)


def test_tick_without_traffic_on_node_does_not_move_it(db, patched_getdb):
    record_user_stats([{"uid": USER_ID, "value": 1024}], NODE_ID)
    stale = datetime.utcnow() - timedelta(minutes=40)
    db.query(NodeUserUsage).filter(NodeUserUsage.node_id == NODE_ID).update({NodeUserUsage.last_seen_at: stale})
    db.commit()

    # Юзер ушёл на другую ноду: тик приносит трафик только по OTHER_NODE_ID.
    record_user_stats([{"uid": USER_ID, "value": 4096}], OTHER_NODE_ID)

    assert usage(db, NODE_ID).last_seen_at == stale
    assert usage(db, OTHER_NODE_ID).last_seen_at > stale


def test_migration_keeps_column_instant_addable():
    """Колонка обязана быть nullable и без server_default.

    Иначе MySQL 9 откажется от ALGORITHM=INSTANT и перестроит node_user_usages
    (~75M строк, 11 ГБ) — это часы простоя учёта трафика. Инвариант ломается
    одной безобидной правкой модели, поэтому проверяется тестом.
    """
    column = NodeUserUsage.__table__.columns["last_seen_at"]
    assert column.nullable is True
    assert column.server_default is None
