"""Идемпотентность купленного БС-пула на границе доставки панели."""

import os
import sys
import types
from datetime import datetime
from uuid import UUID

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

_share_stub = types.ModuleType("app.subscription.share")
_share_stub.generate_v2ray_links = lambda *_args, **_kwargs: []
sys.modules.setdefault("app.subscription.share", _share_stub)
os.environ["DEBUG"] = "false"

from app.db import crud  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.models import User  # noqa: E402
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
