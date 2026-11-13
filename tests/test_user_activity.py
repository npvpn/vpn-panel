"""Пакетное чтение активности: один SELECT, admin scope и HTTP-контракт."""

from __future__ import annotations

import importlib.util
import sys
import types
from datetime import datetime
from pathlib import Path

_share_stub = types.ModuleType("app.subscription.share")
_share_stub.generate_v2ray_links = lambda *_args, **_kwargs: []
sys.modules.setdefault("app.subscription.share", _share_stub)

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db import get_db  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.models import Admin as DBAdmin  # noqa: E402
from app.db.models import User  # noqa: E402
from app.models.admin import Admin  # noqa: E402
from app.services.user_activity import get_users_activity  # noqa: E402

if sys.modules.get("app.subscription.share") is _share_stub:
    del sys.modules["app.subscription.share"]


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        first, second = DBAdmin(username="first"), DBAdmin(username="second")
        session.add_all([first, second])
        session.flush()
        session.add_all(
            [
                User(username="1_1", admin_id=first.id),
                User(username="2_2", admin_id=second.id, online_at=datetime(2026, 11, 13, 10)),
                User(username="3_3"),
            ]
        )
        session.commit()
        yield session
    engine.dispose()


def test_scoped_activity_is_one_read_of_two_columns(db):
    """Чужой admin и отсутствующий пользователь исключены без ORM-графа/записи."""
    statements = []
    event.listen(db.bind, "before_cursor_execute", lambda _c, _cu, sql, *_args: statements.append(sql))
    rows = get_users_activity(db, ["1_1", "2_2", "3_3", "absent", "1_1"], admin_username="first")
    assert rows == [{"username": "1_1", "online_at": None}]
    assert len(statements) == 1
    assert statements[0].startswith("SELECT users.username AS users_username, users.online_at")
    assert not db.new and not db.dirty and not db.deleted


def test_sudo_sees_requested_users_including_without_admin(db):
    """Sudo получает запрошенные строки любого владельца, не всю таблицу."""
    rows = get_users_activity(db, ["2_2", "3_3", "absent"], admin_username=None)
    assert {row["username"]: row["online_at"] for row in rows} == {
        "2_2": datetime(2026, 11, 13, 10),
        "3_3": None,
    }


@pytest.fixture
def client(db, monkeypatch):
    # Загружаем реальный router без тяжёлого app.routers.__init__.
    path = Path(__file__).parents[1] / "app/routers/user_activity.py"
    spec = importlib.util.spec_from_file_location("activity_router_under_test", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    app = FastAPI()
    app.include_router(module.router)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as http:
        yield http, app


def test_http_requires_authentication(client):
    """Без токена реальная auth dependency отвергает запрос."""
    http, _app = client
    assert http.post("/api/users/activity", json={"usernames": ["1_1"]}).status_code == 401


def test_http_preserves_admin_scope_and_serializes_dates(client):
    """Router передаёт права в сервис и сохраняет null/дату online_at."""
    http, app = client
    app.dependency_overrides[Admin.get_current] = lambda: Admin(username="first", is_sudo=False)
    payload = {"usernames": ["1_1", "2_2", "absent"]}
    assert http.post("/api/users/activity", json=payload).json() == {"users": [{"username": "1_1", "online_at": None}]}
    app.dependency_overrides[Admin.get_current] = lambda: Admin(username="sudo", is_sudo=True)
    response = http.post("/api/users/activity", json={"usernames": ["2_2"]})
    assert response.json() == {"users": [{"username": "2_2", "online_at": "2026-11-13T10:00:00"}]}


@pytest.mark.parametrize("usernames", [[], ["x"] * 501, [""], [" "], ["x" * 33], [123]])
def test_http_rejects_invalid_or_unbounded_input(client, usernames):
    """Лимит применяется к сырому запросу до дедупликации, строки валидируются."""
    http, app = client
    app.dependency_overrides[Admin.get_current] = lambda: Admin(username="first", is_sudo=False)
    assert http.post("/api/users/activity", json={"usernames": usernames}).status_code == 422


def test_http_accepts_maximum_batch(client):
    """500 имён принимаются, отсутствующие строки не объявляются offline."""
    http, app = client
    app.dependency_overrides[Admin.get_current] = lambda: Admin(username="first", is_sudo=False)
    response = http.post("/api/users/activity", json={"usernames": [f"u{i}" for i in range(500)]})
    assert response.status_code == 200
    assert response.json() == {"users": []}
