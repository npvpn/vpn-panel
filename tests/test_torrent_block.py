"""Вебхук tblocker и срок, пока локация в подписке остаётся заглушкой."""

from __future__ import annotations

import importlib.util
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

_share_stub = types.ModuleType("app.subscription.share")
_share_stub.generate_v2ray_links = lambda *_args, **_kwargs: []
sys.modules.setdefault("app.subscription.share", _share_stub)

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.db.base import Base
from app.db.models import Node, TorrentUserBlock, User
from app.services.torrent_block import (
    active_blocked_node_ids,
    apply_torrent_event,
    normalize_ip,
    parse_log_email,
)
from app.subscription.torrent_context import TorrentContext
from app.subscription.torrent_context_builder import build_torrent_context

if sys.modules.get("app.subscription.share") is _share_stub:
    del sys.modules["app.subscription.share"]


def test_email_keeps_username_after_the_first_dot():
    assert parse_log_email("15.8691193104_478") == (15, "8691193104_478")
    assert parse_log_email(" 7.user.name ") == (7, "user.name")
    assert parse_log_email("username") is None


def test_ipv4_mapped_address_matches_panel_node_address():
    assert normalize_ip("::ffff:192.0.2.10") == normalize_ip("192.0.2.10")


def test_host_is_affected_when_any_of_its_nodes_is_blocked():
    context = TorrentContext(frozenset({2}), "торрент")
    assert context.affects({"node_ids": [1, 2]})
    assert not context.affects({"node_ids": [1]})
    assert not TorrentContext.empty().affects({"node_ids": [2]})


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(User(username="alice"))
        session.add(Node(name="edge", address="192.0.2.10", port=62050, api_port=62051))
        session.add(Node(name="other", address="192.0.2.11", port=62050, api_port=62051))
        session.commit()
        yield session
    engine.dispose()


def test_block_then_unblock_and_expiry(db):
    now = datetime(2026, 11, 27, 4, 0, 0)
    user_id = db.query(User.id).filter(User.username == "alice").scalar()
    node_id = db.query(Node.id).filter(Node.address == "192.0.2.10").scalar()
    apply_torrent_event(
        db,
        source_ip="192.0.2.10",
        identity=f"{user_id}.alice",
        action="block",
        duration_minutes=10,
        now=now,
    )
    assert active_blocked_node_ids(db, user_id, now) == {node_id}
    row = db.query(TorrentUserBlock).one()
    assert row.blocked_until == now + timedelta(minutes=10)
    assert active_blocked_node_ids(db, user_id, now + timedelta(minutes=10)) == set()

    apply_torrent_event(
        db,
        source_ip="::ffff:192.0.2.10",
        identity=f"{user_id}.alice",
        action="unblock",
        duration_minutes=10,
        now=now,
    )
    assert db.query(TorrentUserBlock).count() == 0


def test_subscription_reads_the_block_until_it_expires(db):
    """Подписка берёт активные ноды из таблицы и имя заглушки из настройки."""
    now = datetime(2026, 11, 27, 4, 0, 0)
    user_id = db.query(User.id).filter(User.username == "alice").scalar()
    node_id = db.query(Node.id).filter(Node.address == "192.0.2.10").scalar()
    apply_torrent_event(
        db,
        source_ip="192.0.2.10",
        identity=f"{user_id}.alice",
        action="block",
        duration_minutes=10,
        now=now,
    )
    settings = {"sub_torrent_block_server_text": ["Заблокировано из-за торрента"]}

    context = build_torrent_context(db, user_id, is_revoked=False, is_expired=False, bot_settings=settings, now=now)
    assert context.blocked_node_ids == frozenset({node_id})
    assert context.stub_text == "Заблокировано из-за торрента"

    revoked = build_torrent_context(db, user_id, is_revoked=True, is_expired=False, bot_settings=settings, now=now)
    expired = build_torrent_context(db, user_id, is_revoked=False, is_expired=True, bot_settings=settings, now=now)
    assert revoked == TorrentContext.empty()
    assert expired == TorrentContext.empty()

    ended = build_torrent_context(
        db,
        user_id,
        is_revoked=False,
        is_expired=False,
        bot_settings=settings,
        now=now + timedelta(minutes=10),
    )
    assert ended.blocked_node_ids == frozenset()
    assert ended.stub_text == ""


def test_unknown_node_and_user_are_rejected(db):
    from app.services.torrent_block import TorrentBlockRejected

    now = datetime(2026, 11, 27, 4, 0, 0)
    with pytest.raises(TorrentBlockRejected) as unknown_node:
        apply_torrent_event(
            db,
            source_ip="198.51.100.9",
            identity="1.alice",
            action="block",
            duration_minutes=10,
            now=now,
        )
    assert unknown_node.value.status_code == 404

    with pytest.raises(TorrentBlockRejected) as unknown_user:
        apply_torrent_event(
            db,
            source_ip="192.0.2.10",
            identity="1.bob",
            action="block",
            duration_minutes=10,
            now=now,
        )
    assert unknown_user.value.status_code == 404


@pytest.fixture
def client(db, monkeypatch):
    path = Path(__file__).parents[1] / "app/routers/torrent_block.py"
    spec = importlib.util.spec_from_file_location("torrent_block_router_under_test", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "TORRENT_WEBHOOK_TOKEN", "secret-token")
    app = FastAPI()
    app.include_router(module.router)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as http:
        yield http


def test_webhook_requires_the_configured_token(client, db):
    user_id = db.query(User.id).filter(User.username == "alice").scalar()
    body = {"username": f"{user_id}.alice", "action": "block", "duration": 10, "ip": "203.0.113.5", "server": "edge"}
    assert client.post("/api/torrent-block", json=body).status_code == 401
    response = client.post(
        "/api/torrent-block",
        json=body,
        headers={"Authorization": "Bearer secret-token", "X-Forwarded-For": "192.0.2.10"},
    )
    assert response.status_code == 200
    assert db.query(TorrentUserBlock).count() == 1


def test_wrong_bearer_of_the_same_length_writes_nothing(client, db):
    """Чужой секрет той же длины не проходит compare_digest и не пишет строку."""
    user_id = db.query(User.id).filter(User.username == "alice").scalar()
    body = {"username": f"{user_id}.alice", "action": "block", "duration": 10}
    response = client.post(
        "/api/torrent-block",
        json=body,
        headers={"Authorization": "Bearer other-secret", "X-Forwarded-For": "192.0.2.10"},
    )
    assert response.status_code == 401
    assert db.query(TorrentUserBlock).count() == 0


def test_empty_webhook_token_closes_the_route(client, db, monkeypatch):
    """Пустой TORRENT_WEBHOOK_TOKEN отвечает 503 и не пишет строку."""
    module = sys.modules["torrent_block_router_under_test"]
    monkeypatch.setattr(module, "TORRENT_WEBHOOK_TOKEN", "")
    user_id = db.query(User.id).filter(User.username == "alice").scalar()
    response = client.post(
        "/api/torrent-block",
        json={"username": f"{user_id}.alice", "action": "block", "duration": 10},
        headers={"Authorization": "Bearer secret-token", "X-Forwarded-For": "192.0.2.10"},
    )
    assert response.status_code == 503
    assert db.query(TorrentUserBlock).count() == 0
