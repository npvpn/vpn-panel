"""Лимит устройств в /sub: ранжирование по first_seen и soft/hard заглушки."""

from __future__ import annotations

import sys
import types
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
from app.db.crud import (  # noqa: E402
    UNKNOWN_DEVICE_HWID,
    count_user_devices,
    get_user_device_by_hwid,
    is_device_within_limit,
    register_user_device,
)
from app.db.models import User, UserDevice  # noqa: E402
from app.subscription.user_info import resolve_device_limit_subscription_state  # noqa: E402

if sys.modules.get("app.subscription.share") is _share_stub:
    del sys.modules["app.subscription.share"]

USER_ID = 1001
BASE_SEEN = datetime(2026, 1, 1, 12, 0, 0)


class FakeSubUser:
    def __init__(self, proxies=None, inbounds=None):
        self.proxies = proxies if proxies is not None else {"vless": {"id": "x"}}
        self.inbounds = inbounds if inbounds is not None else {"vless": ["in"]}

    def model_copy(self, update=None):
        other = FakeSubUser(proxies=dict(self.proxies), inbounds=dict(self.inbounds))
        if update:
            other.proxies = update.get("proxies", other.proxies)
            other.inbounds = update.get("inbounds", other.inbounds)
        return other


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(User(id=USER_ID, username="limit_user", created_at=datetime.utcnow(), device_limit=4))
        session.commit()
        yield session


def _user(db: Session) -> User:
    return db.query(User).filter(User.id == USER_ID).one()


def _add_device(db: Session, hwid: str, *, minutes: int, status: str = "active") -> UserDevice:
    seen = BASE_SEEN + timedelta(minutes=minutes)
    device = UserDevice(
        user_id=USER_ID,
        hwid=hwid,
        status=status,
        first_seen=seen,
        last_seen=seen,
    )
    db.add(device)
    db.commit()
    db.refresh(device)
    return device


def _resolve(db: Session, dbuser: User, hwid: str | None, *, hard_mode: bool):
    user = FakeSubUser()
    return resolve_device_limit_subscription_state(
        user,
        db,
        dbuser,
        False,
        False,
        {"sub_device_limit_hard_mode": hard_mode},
        user_agent="Happ/1.0/Android",
        x_hwid=hwid,
        x_device_os="Android",
        x_ver_os="14",
        x_device_model="Pixel",
    )


def test_is_device_within_limit_first_n_by_first_seen(db):
    devices = [_add_device(db, f"hwid-{i}", minutes=i) for i in range(7)]
    dbuser = _user(db)
    for device in devices[:4]:
        assert is_device_within_limit(db, dbuser, device) is True
    for device in devices[4:]:
        assert is_device_within_limit(db, dbuser, device) is False
    assert is_device_within_limit(db, dbuser, None) is False


def test_is_device_within_limit_without_limit(db):
    dbuser = _user(db)
    dbuser.device_limit = None
    db.commit()
    device = _add_device(db, "hwid-a", minutes=0)
    assert is_device_within_limit(db, dbuser, device) is True
    assert is_device_within_limit(db, dbuser, None) is True


def test_existing_extras_soft_overlay_hard_only(db):
    devices = [_add_device(db, f"hwid-{i}", minutes=i) for i in range(7)]
    dbuser = _user(db)

    in_limit_user, limited, hard, unsupported = _resolve(db, dbuser, devices[0].hwid, hard_mode=False)
    assert (limited, hard, unsupported) == (False, False, False)
    assert in_limit_user.proxies

    extra_soft_user, limited, hard, unsupported = _resolve(db, dbuser, devices[4].hwid, hard_mode=False)
    assert (limited, hard, unsupported) == (True, False, False)
    assert extra_soft_user.proxies

    extra_hard_user, limited, hard, unsupported = _resolve(db, dbuser, devices[6].hwid, hard_mode=True)
    assert (limited, hard, unsupported) == (True, True, False)
    assert extra_hard_user.proxies == {}


def test_exactly_at_limit_known_device_is_clean(db):
    devices = [_add_device(db, f"hwid-{i}", minutes=i) for i in range(4)]
    dbuser = _user(db)
    user, limited, hard, unsupported = _resolve(db, dbuser, devices[3].hwid, hard_mode=True)
    assert (limited, hard, unsupported) == (False, False, False)
    assert user.proxies


def test_new_hwid_at_limit_soft_adds_overlay(db):
    for i in range(4):
        _add_device(db, f"hwid-{i}", minutes=i)
    dbuser = _user(db)
    user, limited, hard, unsupported = _resolve(db, dbuser, "hwid-new", hard_mode=False)
    assert (limited, hard, unsupported) == (True, False, False)
    assert user.proxies
    assert count_user_devices(db, dbuser) == 5
    assert get_user_device_by_hwid(db, dbuser, "hwid-new") is not None


def test_new_hwid_at_limit_hard_does_not_add(db):
    for i in range(4):
        _add_device(db, f"hwid-{i}", minutes=i)
    dbuser = _user(db)
    user, limited, hard, unsupported = _resolve(db, dbuser, "hwid-new", hard_mode=True)
    assert (limited, hard, unsupported) == (True, True, False)
    assert user.proxies == {}
    assert count_user_devices(db, dbuser) == 4
    assert get_user_device_by_hwid(db, dbuser, "hwid-new") is None


def test_no_device_limit_adds_and_not_limited(db):
    dbuser = _user(db)
    dbuser.device_limit = None
    db.commit()
    user, limited, hard, unsupported = _resolve(db, dbuser, "hwid-new", hard_mode=True)
    assert (limited, hard, unsupported) == (False, False, False)
    assert user.proxies
    assert get_user_device_by_hwid(db, dbuser, "hwid-new") is not None


def test_register_soft_allows_over_limit_hard_blocks(db):
    dbuser = _user(db)
    for i in range(4):
        _add_device(db, f"hwid-{i}", minutes=i)

    registered, unsupported = register_user_device(db, dbuser, "soft-new", None, None, None, "Happ", hard_mode=False)
    assert (registered, unsupported) == (True, False)
    assert get_user_device_by_hwid(db, dbuser, "soft-new") is not None

    registered, unsupported = register_user_device(db, dbuser, "hard-new", None, None, None, "Happ", hard_mode=True)
    assert (registered, unsupported) == (False, False)
    assert get_user_device_by_hwid(db, dbuser, "hard-new") is None


def test_unknown_hwid_constant_used_for_empty_header(db):
    dbuser = _user(db)
    registered, unsupported = register_user_device(db, dbuser, None, None, None, None, "Happ/1.0", hard_mode=False)
    assert (registered, unsupported) == (True, False)
    assert get_user_device_by_hwid(db, dbuser, UNKNOWN_DEVICE_HWID) is not None
