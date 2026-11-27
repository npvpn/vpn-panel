"""Связи хостов и ролей в карточке ноды sudo-оператора."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from tests.test_host_balancing_db import Base  # bootstrap panel test DB modules

# isort: split
from app.db.models import Bot, CascadeRoute, Node, ProxyHost, ProxyInbound, XrayTemplate, XrayTemplateVersion
from app.models.admin import Admin
from app.models.node import NodeRole, NodeStatus


@pytest.fixture
def topology(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    spec = importlib.util.spec_from_file_location(
        "node_hosts_api_test", Path(__file__).parents[1] / "app/routers/node.py"
    )
    route = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(route)
    api = FastAPI()
    api.include_router(route.router)
    monkeypatch.setattr(Admin, "get_admin", lambda token, _: SimpleNamespace(is_sudo=token == "sudo"))
    monkeypatch.setattr(route.xray, "config", SimpleNamespace(inbounds_by_tag={"A": {}, "B": {}}), raising=False)

    def request_db():
        with Session(engine) as session:
            yield session

    api.dependency_overrides[route.get_db] = request_db
    with Session(engine) as db, TestClient(api, headers={"Authorization": "Bearer sudo"}) as client:
        db.add_all(ProxyInbound(tag=tag) for tag in ["A", "B", "CASCADE", "OLD"])
        db.add_all(
            Node(id=i, name=f"n{i}", address=f"192.0.2.{i}", port=62050, api_port=62051, status=NodeStatus.connected)
            for i in range(1, 6)
        )
        db.commit()
        yield db, client
    engine.dispose()


def host(db, id_, *, nodes=(), selected=(), address="", inbound="A", **fields):
    row = ProxyHost(
        id=id_,
        remark=f"H{id_}",
        address=address,
        inbound_tag=inbound,
        nodes=[db.get(Node, i) for i in nodes],
        balancer_nodes=[db.get(Node, i) for i in selected],
        balancer_nodes_source="selected" if selected else "host",
        **fields,
    )
    db.add(row)
    db.flush()
    return row


def test_configured_entry_exit_link_and_disabled_relations(topology):
    db, client = topology
    db.get(Node, 1).role = NodeRole.entry
    db.get(Node, 3).status = NodeStatus.disabled
    db.add(CascadeRoute(entry_node_id=1, exit_node_id=2, entry_inbound_tag="A", cascade_inbound_tag="CASCADE"))
    host(db, 11, nodes=[3], selected=[1, 3])
    host(db, 12, nodes=[1], inbound="B", is_disabled=True)
    host(db, 13, nodes=[1], address="192.0.2.1")
    host(db, 14, nodes=[1], address="mask.example")
    host(db, 15, address="192.0.2.1")  # Совпадение с адресом ноды без явной связи.
    host(db, 16, nodes=[1], selected=[4], inbound="B")
    host(db, 17, nodes=[1], selected=[1], inbound="B")
    host(db, 18, nodes=[2], inbound="B")  # Эта же выходная нода в другом хосте прямая.
    db.commit()

    def roles(node_id):
        response = client.get(f"/api/node/{node_id}/hosts")
        assert response.status_code == 200
        return {r["host_id"]: r["roles"] for r in response.json()["hosts"]}

    assert roles(1) == {
        11: ["entry"],
        12: ["direct"],
        13: ["entry"],
        14: ["linked"],
        16: ["linked"],
        17: ["entry", "linked"],
    }
    assert roles(2) == {11: ["exit"], 13: ["exit"], 18: ["direct"]}
    assert roles(3) == {11: ["entry", "linked"]}
    assert roles(4) == {16: ["entry"]}
    assert roles(5) == {}
    rows = client.get("/api/node/1/hosts").json()["hosts"]
    assert [r["host_id"] for r in rows] == [11, 13, 14, 16, 17, 12]
    assert rows[-1] == {
        "host_id": 12,
        "remark": "H12",
        "inbound_tag": "B",
        "is_disabled": True,
        "roles": ["direct"],
        "sources": [],
    }


def test_static_shared_address_does_not_identify_an_entry(topology):
    db, client = topology
    db.get(Node, 3).address = "192.0.2.1"
    db.get(Node, 1).role = NodeRole.entry
    db.add(CascadeRoute(entry_node_id=1, exit_node_id=2, entry_inbound_tag="A", cascade_inbound_tag="CASCADE"))
    host(db, 10, nodes=[1, 3], address="192.0.2.1")
    db.commit()
    for node_id in (1, 3):
        assert client.get(f"/api/node/{node_id}/hosts").json()["hosts"][0]["roles"] == ["linked"]
    assert client.get("/api/node/2/hosts").json()["hosts"] == []


@pytest.mark.parametrize("bot_count", [0, 1, 3])
def test_composite_sources_follow_template_visibility_and_common_audience(topology, bot_count):
    db, client = topology
    bots = [Bot(username=f"bot{i}") for i in range(bot_count)]
    db.add_all(bots)
    first, other = bots[:1], bots[-1:]
    tpl = XrayTemplate(slug="auto", title="Auto")
    db.add(tpl)
    db.flush()
    group = {"selector": {"type": "sameTagAsRecipient"}, "tagPrefix": "proxy", "selectFrom": "HIDDEN"}
    db.add(XrayTemplateVersion(template_id=tpl.id, version=1, body=json.dumps({"npvpn": {"injectHosts": [group]}})))
    for id_, fields in [
        (21, {"bots": first, "nodes": [1]}),
        (22, {"bots": other, "selected": [1]}),
        (23, {"bots": first, "nodes": [1], "is_disabled": True}),
        (24, {"bots": first, "nodes": [1], "inbound": "OLD"}),
        (25, {"bots": first, "nodes": [1], "client_config_id": tpl.id}),
    ]:
        host(db, id_, group_tag="pool", is_hidden=True, **fields)
    host(db, 26, nodes=[1], bots=first, group_tag="pool")  # видимый источник исключён селектором
    host(db, 27, nodes=[4], bots=first, group_tag="pool", client_config_id=tpl.id)
    db.commit()
    queries = []

    @event.listens_for(db.get_bind(), "before_cursor_execute")
    def record(*args):
        queries.append(args[2])

    response = client.get("/api/node/1/hosts")
    assert response.status_code == 200
    assert len(queries) <= 10  # Независимо от числа ботов и составных хостов.
    composite = next(row for row in response.json()["hosts"] if row["host_id"] == 27)
    sources = [{"host_id": 21, "remark": "H21", "roles": ["direct"]}]
    if bot_count <= 1:
        sources.append({"host_id": 22, "remark": "H22", "roles": ["entry"]})
    assert composite["sources"] == sources
    assert composite["roles"] == (["direct", "entry"] if bot_count <= 1 else ["direct"])
    assert client.get("/api/node/4/hosts").json()["hosts"] == []  # Собственный outbound выключен.


def test_host_inventory_requires_sudo_and_distinguishes_unknown_node(topology):
    _, client = topology
    assert client.get("/api/node/1/hosts", headers={"Authorization": ""}).status_code == 401
    assert client.get("/api/node/1/hosts", headers={"Authorization": "Bearer reader"}).status_code == 403
    assert client.get("/api/node/999/hosts").status_code == 404
    assert client.get("/api/node/1/hosts").json()["hosts"] == []


def test_composite_inherits_only_roles_of_selected_endpoints(topology):
    db, client = topology
    disabled = db.get(Node, 1)
    disabled.status = NodeStatus.disabled
    disabled.role = NodeRole.entry
    db.add(CascadeRoute(entry_node_id=1, exit_node_id=2, entry_inbound_tag="A", cascade_inbound_tag="CASCADE"))
    host(db, 31, nodes=[5], selected=[1, 3])
    group = {"selector": {"type": "ids", "values": [31]}, "tagPrefix": "peer", "selectFrom": "ALL"}
    host(db, 32, nodes=[3], host_injection={"injectHosts": [group], "addVirtualHostAsOutbound": True})
    db.commit()

    def rows(node_id):
        result = client.get(f"/api/node/{node_id}/hosts").json()
        assert result["incomplete_host_ids"] == []
        return {row["host_id"]: row for row in result["hosts"]}

    assert set(rows(1)) == {31}
    assert set(rows(2)) == {31}
    running = rows(3)[32]
    assert running["roles"] == ["direct", "entry"]
    assert running["sources"] == [{"host_id": 31, "remark": "H31", "roles": ["entry"]}]
    assert rows(5)[32]["roles"] == ["linked"]


def test_invalid_config_and_collision_return_partial_inventory(topology):
    db, client = topology
    host(db, 41, nodes=[1])
    host(db, 42, selected=[1], host_injection={"broken": True}).remark = "H41"
    group = {"selector": {"type": "ids", "values": [41]}, "tagPrefix": "duplicate", "selectFrom": "ALL"}
    host(db, 43, nodes=[1], host_injection={"injectHosts": [group, group]})
    host(
        db,
        44,
        host_injection={
            "injectHosts": [
                {"useHostRemarkAsTag": True, "selectFrom": "ALL", "selector": {"type": "ids", "values": [41, 42]}}
            ]
        },
    )
    db.commit()
    response = client.get("/api/node/1/hosts")
    assert response.status_code == 200
    result = response.json()
    assert result["incomplete_host_ids"] == [42, 43, 44]
    rows = {row["host_id"]: row for row in result["hosts"]}
    assert rows[41]["roles"] == ["direct"]
    assert rows[42]["roles"] == ["linked"]
    assert rows[43]["roles"] == ["linked"]
    assert rows[44]["sources"] == [{"host_id": 41, "remark": "H41", "roles": ["direct"]}]
