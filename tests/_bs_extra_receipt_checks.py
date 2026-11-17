"""Идемпотентность купленного БС-пула на границе доставки панели."""

import os
import sys
import threading
import types
from datetime import datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import MetaData, create_engine, event, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

_share_stub = types.ModuleType("app.subscription.share")
_share_stub.generate_v2ray_links = lambda *_args, **_kwargs: []
sys.modules.setdefault("app.subscription.share", _share_stub)
os.environ["DEBUG"] = "false"

from app.db import crud  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.models import PanelDeliveryReceipt, User  # noqa: E402
from app.models.user import UserBsExtraModify  # noqa: E402

if sys.modules.get("app.subscription.share") is _share_stub:
    del sys.modules["app.subscription.share"]


GB = 1024**3
USER_ID = 90210
FIRST_OPERATION = UUID("ef2b5462-7d35-4acb-bbf3-36f5ad2b4c3f")
SECOND_OPERATION = UUID("6dc45748-2ce0-4b2c-960e-a0e58342d072")


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(User(id=USER_ID, username="delivery_90210", created_at=datetime.utcnow()))
        session.commit()
        yield session
    engine.dispose()


def user(db):
    return db.query(User).filter(User.id == USER_ID).one()


def test_same_operation_id_increments_bs_extra_once(db):
    """Повтор после падения воркера возвращает результат, но не продаёт ГБ дважды."""
    first = crud.modify_user_bs_extra(db, user(db), delta_bytes=GB, operation_id=FIRST_OPERATION)
    second = crud.modify_user_bs_extra(db, user(db), delta_bytes=GB, operation_id=FIRST_OPERATION)

    assert first.bs_extra == GB
    assert second.bs_extra == GB
    assert user(db).bs_extra == GB


def test_different_operation_ids_increment_bs_extra_independently(db):
    crud.modify_user_bs_extra(db, user(db), delta_bytes=GB, operation_id=FIRST_OPERATION)
    result = crud.modify_user_bs_extra(db, user(db), delta_bytes=GB, operation_id=SECOND_OPERATION)

    assert result.bs_extra == 2 * GB


def test_payload_accepts_uuid_operation_id():
    payload = UserBsExtraModify(delta_bytes=GB, operation_id=str(FIRST_OPERATION))

    assert payload.operation_id == FIRST_OPERATION


@pytest.fixture
def mysql_engine():
    """Каждый тест получает отдельную пустую БД явно заданного тестового сервера."""
    dsn = os.environ.get("TEST_MYSQL_DSN")
    if not dsn:
        pytest.skip("TEST_MYSQL_DSN is required for MySQL concurrency checks")
    admin = create_engine(dsn)
    database = f"test_receipt_{uuid4().hex}"
    with admin.begin() as connection:
        connection.execute(text(f"CREATE DATABASE `{database}`"))
    engine = create_engine(admin.url.set(database=database), isolation_level="REPEATABLE READ")
    try:
        metadata = MetaData()
        for table in Base.metadata.sorted_tables:
            table.to_metadata(metadata)
        # ORM keeps SQLite's NOCASE; MySQL migrations use a native ci collation.
        # Work on copied DDL so other tests retain their original metadata.
        for table in metadata.tables.values():
            for column in table.columns:
                if getattr(column.type, "collation", None) == "NOCASE":
                    column.type = column.type.copy()
                    column.type.collation = "utf8mb4_unicode_ci"
        metadata.create_all(engine)
        with Session(engine) as db:
            db.add(User(id=90210, username="receipt_test", created_at=datetime.utcnow()))
            db.commit()
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f"DROP DATABASE `{database}`"))
        admin.dispose()


def test_distinct_concurrent_receipts_do_not_deadlock(mysql_engine):
    """Две покупки одного пользователя обе начисляются без S→X deadlock."""
    loaded = threading.Barrier(2)
    inserted = threading.Barrier(2)
    failures = []

    def after_insert(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.startswith("INSERT INTO panel_delivery_receipts"):
            try:
                inserted.wait(timeout=0.5)
            except threading.BrokenBarrierError:
                pass

    event.listen(mysql_engine, "after_cursor_execute", after_insert)

    def purchase():
        try:
            with Session(mysql_engine) as db:
                user = db.get(User, 90210)
                loaded.wait(timeout=5)
                crud.modify_user_bs_extra(db, user, delta_bytes=GB, operation_id=uuid4())
        except Exception as exc:
            failures.append(exc)

    threads = [threading.Thread(target=purchase) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert not any(thread.is_alive() for thread in threads)
    assert not failures, failures
    with Session(mysql_engine) as db:
        assert db.get(User, 90210).bs_extra == 2 * GB
        assert len(db.scalars(select(PanelDeliveryReceipt)).all()) == 2


def test_repeat_after_older_snapshot_returns_committed_receipt(mysql_engine):
    """Повтор видит receipt, зафиксированный после создания RR-снимка запроса."""
    operation_id = uuid4()
    with Session(mysql_engine) as older, Session(mysql_engine) as writer:
        old_user = older.get(User, 90210)
        crud.modify_user_bs_extra(writer, writer.get(User, 90210), delta_bytes=GB, operation_id=operation_id)
        result = crud.modify_user_bs_extra(older, old_user, delta_bytes=GB, operation_id=operation_id)
        assert result.bs_extra == GB
    with Session(mysql_engine) as db:
        assert db.get(User, 90210).bs_extra == GB
        assert len(db.scalars(select(PanelDeliveryReceipt)).all()) == 1
