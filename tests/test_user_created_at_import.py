"""Создание пользователя через API сохраняет переданную дату регистрации."""

from __future__ import annotations

import sys
import types
from datetime import UTC, datetime, timedelta, timezone
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
from app.utils.jwt import get_subscription_payload  # noqa: E402

if sys.modules.get("app.subscription.share") is share_stub:
    del sys.modules["app.subscription.share"]


def _prepare(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        xray,
        "config",
        SimpleNamespace(inbounds_by_protocol={}, inbounds_by_tag={}),
        raising=False,
    )
    monkeypatch.setattr("app.utils.jwt.get_secret_key", lambda: "test-secret")
    monkeypatch.setattr(
        "app.services.panel_settings.get_cached_legacy_subscription_secret_keys",
        lambda: (),
    )
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine


def _payload(username: str, created_at: str) -> UserCreate:
    return UserCreate.model_validate(
        {
            "username": username,
            "proxies": {"vless": {}},
            "inbounds": {"vless": []},
            "created_at": created_at,
        }
    )


def test_create_user_persists_imported_registration_date(monkeypatch: pytest.MonkeyPatch):
    engine = _prepare(monkeypatch)
    try:
        with Session(engine) as session:
            user = crud.create_user(session, _payload("123_456", "2024-02-03T04:05:06"))
            assert user.created_at == datetime(2024, 2, 3, 4, 5, 6)
    finally:
        engine.dispose()


def test_offset_registration_date_is_stored_in_utc_and_the_link_opens(monkeypatch: pytest.MonkeyPatch):
    engine = _prepare(monkeypatch)
    try:
        created_at = datetime(2024, 2, 3, 7, 5, 6, tzinfo=timezone(timedelta(hours=3))).isoformat()
        with Session(engine) as session:
            user = crud.create_user(session, _payload("123_456", created_at))
            assert user.created_at == datetime(2024, 2, 3, 4, 5, 6)
            # Та же проверка, что resolve_subscription_context: токен новее записи.
            token = get_subscription_payload(user.subscription_token)
            assert token is not None
            opened = crud.get_user(session, token["username"])
            assert opened is not None
            assert opened.username == "123_456"
            assert not (opened.created_at and token.get("created_at") and opened.created_at > token["created_at"])
    finally:
        engine.dispose()


def test_future_registration_date_is_rejected(monkeypatch: pytest.MonkeyPatch):
    engine = _prepare(monkeypatch)
    try:
        future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
        with Session(engine) as session:
            with pytest.raises(ValueError, match="future"):
                crud.create_user(session, _payload("123_456", future))
            assert crud.get_user(session, "123_456") is None
    finally:
        engine.dispose()
