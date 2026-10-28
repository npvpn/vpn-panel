"""Независимая связь, совместимость записи и атомарная проверка настроек."""

from __future__ import annotations

import sys
import types

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

for _name, _module in list(sys.modules.items()):
    if _name.startswith("app.") and not hasattr(_module, "__file__") and not hasattr(_module, "__path__"):
        del sys.modules[_name]

stub = types.ModuleType("app.subscription.share")
stub.generate_v2ray_links = lambda *a, **k: []
sys.modules.setdefault("app.subscription.share", stub)
from app.db import crud
from app.db.base import Base
from app.db.models import Node, ProxyHost, ProxyInbound
from app.models.node import NodeStatus
from app.models.proxy import ProxyHost as Payload

if sys.modules.get("app.subscription.share") is stub:
    del sys.modules["app.subscription.share"]


@pytest.fixture
def db():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def enable_fk(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(ProxyInbound(tag="VLESS"))
        db.add_all(
            [
                Node(
                    id=i, name=f"n{i}", address=f"192.0.2.{i}", port=62050, api_port=62051, status=NodeStatus.connected
                )
                for i in (1, 2, 9)
            ]
        )
        db.commit()
        yield db


def payload(**kw):
    return Payload.model_validate(
        {
            "remark": "NL",
            "address": "fallback.example",
            "node_ids": [9],
            "balancer_nodes_source": "selected",
            "balancer_node_ids": [2, 1],
            "balancing": {"strategy": "leastLoad"},
            **kw,
        }
    )


def test_create_independent_pool_and_roundtrip(db):
    h = crud.add_host(db, "VLESS", payload())[0]
    assert h.node_ids == [9]
    assert sorted(h.balancer_node_ids) == [1, 2]
    r = Payload.model_validate(h)
    assert r.balancing.settings.expected == 2
    assert r.balancer_nodes_source == "selected"


def test_legacy_update_preserves_new_settings(db):
    h = crud.add_host(db, "VLESS", payload())[0]
    crud.update_hosts(db, "VLESS", [Payload(id=h.id, remark="Renamed", address="fallback.example", node_ids=[9])])
    db.expire_all()
    h = db.get(ProxyHost, h.id)
    assert h.balancing["strategy"] == "leastLoad"
    assert h.balancer_nodes_source == "selected"
    assert sorted(h.balancer_node_ids) == [1, 2]


def test_explicit_reset_preserves_linked_nodes(db):
    h = crud.add_host(db, "VLESS", payload())[0]
    crud.update_hosts(
        db, "VLESS", [payload(id=h.id, balancing=None, balancer_nodes_source="host", balancer_node_ids=[])]
    )
    assert h.balancing is None
    assert h.node_ids == [9] and h.balancer_node_ids == []


def test_invalid_second_host_does_not_change_first(db):
    h = crud.add_host(db, "VLESS", payload())[0]
    with pytest.raises(ValueError):
        crud.update_hosts(db, "VLESS", [payload(id=h.id, remark="changed"), payload(balancer_node_ids=[999])])
    assert h.remark == "NL"
    assert not db.dirty and not db.new


def test_disabled_new_node_rejected_existing_can_be_saved(db):
    h = crud.add_host(db, "VLESS", payload())[0]
    db.get(Node, 1).status = NodeStatus.disabled
    db.commit()
    crud.update_hosts(db, "VLESS", [payload(id=h.id, remark="edited")])
    assert h.remark == "edited"
    with pytest.raises(ValueError):
        crud.add_host(db, "VLESS", payload())


def test_delete_last_entry_does_not_delete_host_or_change_mode(db):
    h = crud.add_host(db, "VLESS", payload(balancer_node_ids=[1]))[0]
    db.delete(db.get(Node, 1))
    db.commit()
    db.expire_all()
    assert h.balancer_node_ids == []
    assert h.balancer_nodes_source == "selected"
    assert h.node_ids == [9]


def test_empty_selected_pool_rejected_on_creation(db):
    with pytest.raises(ValueError):
        crud.add_host(db, "VLESS", payload(balancer_node_ids=[]))


def test_snapshot_uses_explicit_entries_even_with_static_address(db):
    from app.jobs.snapshot_host_composition import _host_payload

    h = crud.add_host(db, "VLESS", payload())[0]
    assert _host_payload(h) == [{"node_id": 1, "address": "192.0.2.1"}, {"node_id": 2, "address": "192.0.2.2"}]


def test_entry_pool_pin_list_respects_tenant_and_static_address(db, monkeypatch):
    from app.db.models import Bot, User
    from app.services import address_history

    bot = Bot(username="own")
    other = Bot(username="other")
    db.add_all([bot, other])
    db.commit()
    h = crud.add_host(db, "VLESS", payload(bot_usernames=["own"]))[0]
    user = User(username="test-user", bot=bot)
    foreign = User(username="foreign-user", bot=other)
    db.add_all([user, foreign])
    db.commit()
    monkeypatch.setattr(address_history, "_visible_inbound_tags", lambda _: {"VLESS"})
    result = address_history.list_pinnable_hosts(db, user)
    assert len(result) == 1 and result[0].host_id == h.id
    assert [n.node_id for n in result[0].nodes] == [1, 2]
    assert address_history.list_pinnable_hosts(db, foreign) == []


def test_batch_rolls_back_all_inbounds_on_invalid_second_entry(db):
    first = crud.add_host(db, "VLESS", payload())[0]
    second = crud.add_host(db, "SECOND", payload())[-1]
    first_id, second_id = first.id, second.id
    with pytest.raises(ValueError):
        crud.update_hosts_batch(
            db,
            {
                "VLESS": [payload(id=first_id, remark="changed", balancer_node_ids=[2])],
                "SECOND": [payload(id=second_id, balancer_node_ids=[999])],
            },
        )
    db.expire_all()
    assert db.get(ProxyHost, first_id).remark == "NL"
    assert db.get(ProxyHost, first_id).balancer_node_ids == [1, 2]
    assert db.get(ProxyHost, second_id).balancer_node_ids == [1, 2]


def test_batch_moves_host_preserving_identity_and_balancing(db):
    host = crud.add_host(db, "VLESS", payload())[0]
    host_id = host.id
    data = Payload.model_validate(host)
    crud.update_hosts_batch(db, {"VLESS": [], "SECOND": [data]})
    db.expire_all()
    moved = db.get(ProxyHost, host_id)
    assert moved.inbound_tag == "SECOND"
    assert moved.balancer_node_ids == [1, 2]
    assert moved.node_ids == [9]
    assert moved.balancing["strategy"] == "leastLoad"
    assert crud.get_hosts(db, "VLESS") == []


def test_batch_rejects_duplicate_ids_without_committing(db):
    host = crud.add_host(db, "VLESS", payload())[0]
    with pytest.raises(ValueError, match="duplicate"):
        crud.update_hosts_batch(db, {"VLESS": [payload(id=host.id)], "SECOND": [payload(id=host.id)]})
    assert db.get(ProxyHost, host.id).inbound_tag == "VLESS"
