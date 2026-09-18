"""Суточный снимок состава хостов: crud.write_host_composition_snapshot и соседи (NPVPN-2072)."""

from __future__ import annotations

import sys
import types
from datetime import datetime

import pytest

# app/__init__.py тяжёлый, а app.subscription.share тянет за собой весь стек
# генерации ссылок — тот же обход, что в test_address_rotation_endpoint.py и
# test_get_weight_snapshot.py.
for _name, _module in list(sys.modules.items()):
    if _name.startswith("app.") and not hasattr(_module, "__file__") and not hasattr(_module, "__path__"):
        del sys.modules[_name]

_share_stub = types.ModuleType("app.subscription.share")
_share_stub.generate_v2ray_links = lambda *args, **kwargs: []
sys.modules.setdefault("app.subscription.share", _share_stub)

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.crud import (  # noqa: E402
    get_host_composition,
    prune_host_composition_snapshots,
    write_host_composition_snapshot,
)
from app.db.models import HostCompositionSnapshot, Node, ProxyHost, ProxyInbound  # noqa: E402
from app.jobs.snapshot_host_composition import _host_payload  # noqa: E402
from app.xray.host_addresses import resolve_host_addresses, resolve_host_node_ids  # noqa: E402

if sys.modules.get("app.subscription.share") is _share_stub:
    del sys.modules["app.subscription.share"]


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _make_node(db, name: str, address: str) -> Node:
    node = Node(name=name, address=address, port=62050, api_port=62051, created_at=datetime.utcnow())
    db.add(node)
    db.commit()
    db.refresh(node)
    return node


def _make_host(db, *, address: str = "", nodes: list[Node] | None = None) -> ProxyHost:
    inbound_tag = f"tag-{db.query(ProxyInbound).count()}"
    db.add(ProxyInbound(tag=inbound_tag))
    db.commit()
    host = ProxyHost(remark="r", address=address, inbound_tag=inbound_tag)
    if nodes:
        host.nodes = nodes
    db.add(host)
    db.commit()
    db.refresh(host)
    return host


def _payload_for(host: ProxyHost) -> list[dict]:
    """То же построение, что использует джоба: node_id спарен с address по нодам."""
    addresses = resolve_host_addresses(host)
    node_ids = resolve_host_node_ids(host)
    return [{"node_id": nid, "address": addr} for nid, addr in zip(node_ids, addresses, strict=True)]


def test_snapshot_records_visible_nodes_and_addresses(db):
    """Состав снимается тем же способом, каким адреса попадают в подписку."""
    node1 = _make_node(db, "nl-1", "1.2.3.4")
    node2 = _make_node(db, "nl-2", "5.6.7.8")
    host = _make_host(db, nodes=[node1, node2])

    expected = _payload_for(host)
    assert expected == [
        {"node_id": node1.id, "address": "1.2.3.4"},
        {"node_id": node2.id, "address": "5.6.7.8"},
    ]

    write_host_composition_snapshot(db, 10, host.id, expected)

    composition = get_host_composition(db, 10)
    assert composition == {host.id: expected}


def test_snapshot_is_idempotent_within_a_day(db):
    """Повторный проход в те же сутки не плодит строк и не меняет payload."""
    node = _make_node(db, "nl-1", "1.2.3.4")
    host = _make_host(db, nodes=[node])

    first_payload = [{"node_id": node.id, "address": "1.2.3.4"}]
    write_host_composition_snapshot(db, 10, host.id, first_payload)

    # Состав "изменился" (например, ноду переадресовали) — но сутки те же, поэтому
    # уже зафиксированная запись не должна поменяться.
    changed_payload = [{"node_id": node.id, "address": "9.9.9.9"}]
    write_host_composition_snapshot(db, 10, host.id, changed_payload)

    rows = db.query(HostCompositionSnapshot).filter(HostCompositionSnapshot.epoch_index == 10).all()
    assert len(rows) == 1
    assert rows[0].payload == first_payload
    assert get_host_composition(db, 10) == {host.id: first_payload}


def test_prune_removes_snapshots_older_than_retention(db):
    """Архив режется по границе epoch_index - retention_days."""
    node = _make_node(db, "nl-1", "1.2.3.4")
    host = _make_host(db, nodes=[node])
    payload = [{"node_id": node.id, "address": "1.2.3.4"}]

    write_host_composition_snapshot(db, 5, host.id, payload)  # старше горизонта
    write_host_composition_snapshot(db, 9, host.id, payload)  # ровно на границе
    write_host_composition_snapshot(db, 10, host.id, payload)  # свежий

    prune_host_composition_snapshots(db, 10, retention_days=1)

    remaining = {row.epoch_index for row in db.query(HostCompositionSnapshot).all()}
    assert remaining == {9, 10}


def test_snapshot_survives_host_without_nodes(db):
    """Хост без привязанных нод даёт пустой payload, а не падение."""
    host = _make_host(db, nodes=None)

    payload = _payload_for(host)
    assert payload == []

    write_host_composition_snapshot(db, 10, host.id, payload)

    assert get_host_composition(db, 10) == {host.id: []}


def test_static_address_host_has_no_node_correlation(db):
    """host.address статический: node_id -> None, а не случайное сопоставление по индексу.

    Число адресов (2, через запятую) и число привязанных нод (3) НАРОЧНО не
    совпадают — если бы код зиповал node_ids с адресами как для нодового случая,
    он бы либо упал (strict=True), либо молча приписал адресу чужую ноду. Вызываем
    ровно ту функцию, что использует джоба (_host_payload), а не копию её логики —
    иначе тест проверял бы сам себя, а не продакшен-код.
    """
    node1 = _make_node(db, "nl-1", "1.2.3.4")
    node2 = _make_node(db, "nl-2", "5.6.7.8")
    node3 = _make_node(db, "nl-3", "9.9.9.9")
    host = _make_host(db, address="static-a.example, static-b.example", nodes=[node1, node2, node3])

    payload = _host_payload(host)

    assert payload == [
        {"node_id": None, "address": "static-a.example"},
        {"node_id": None, "address": "static-b.example"},
    ]

    write_host_composition_snapshot(db, 10, host.id, payload)

    assert get_host_composition(db, 10) == {host.id: payload}
