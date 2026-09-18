"""Ручная ротация адресов юзера (NPVPN-2072)."""

from __future__ import annotations

import sys
import types

# app/__init__.py тяжёлый, а app.subscription.share тянет за собой весь стек
# генерации ссылок — тот же обход, что в test_hosting_traffic_limit.py и
# test_address_subset_migration.py.
for _name, _module in list(sys.modules.items()):
    if _name.startswith("app.") and not hasattr(_module, "__file__") and not hasattr(_module, "__path__"):
        del sys.modules[_name]

_share_stub = types.ModuleType("app.subscription.share")
_share_stub.generate_v2ray_links = lambda *args, **kwargs: []
sys.modules.setdefault("app.subscription.share", _share_stub)

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.crud import rotate_user_addresses  # noqa: E402
from app.db.models import User  # noqa: E402

if sys.modules.get("app.subscription.share") is _share_stub:
    del sys.modules["app.subscription.share"]


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_rotation_starts_from_zero(db):
    user = User(username="u1")
    db.add(user)
    db.commit()
    assert user.address_rotation_offset == 0


def test_rotation_increments(db):
    user = User(username="u1")
    db.add(user)
    db.commit()
    rotate_user_addresses(db, user)
    assert user.address_rotation_offset == 1
    rotate_user_addresses(db, user)
    assert user.address_rotation_offset == 2


def test_rotation_survives_null_offset(db):
    """Строки, созданные до миграции, могут прийти с NULL — не падаем."""
    user = User(username="u1")
    db.add(user)
    db.commit()
    user.address_rotation_offset = None
    rotate_user_addresses(db, user)
    assert user.address_rotation_offset == 1
