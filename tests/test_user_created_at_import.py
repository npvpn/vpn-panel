"""Создание пользователя через API сохраняет переданную дату регистрации."""

from __future__ import annotations

import sys
import types
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

share_stub = types.ModuleType("app.subscription.share")
share_stub.generate_v2ray_links = lambda *_args, **_kwargs: []
sys.modules.setdefault("app.subscription.share", share_stub)

from app import xray  # noqa: E402
from app.db import crud  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.models.user import UserCreate  # noqa: E402

if sys.modules.get("app.subscription.share") is share_stub:
    del sys.modules["app.subscription.share"]


def test_create_user_persists_imported_registration_date(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        xray,
        "config",
        SimpleNamespace(inbounds_by_protocol={}, inbounds_by_tag={}),
        raising=False,
    )
    monkeypatch.setattr(crud, "create_subscription_token", lambda _username: "test-token")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    try:
        payload = UserCreate.model_validate(
            {
                "username": "123_456",
                "proxies": {"vless": {}},
                "inbounds": {"vless": []},
                "created_at": "2024-02-03T04:05:06",
            }
        )
        with Session(engine) as session:
            user = crud.create_user(session, payload)
            assert user.created_at == datetime(2024, 2, 3, 4, 5, 6)
    finally:
        engine.dispose()
