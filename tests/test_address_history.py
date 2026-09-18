"""address_history.reconstruct: восстановление выдачи адресов задним числом (NPVPN-2072).

Смысловое ядро журнала: то, ради чего собираются суточные снимки состава хостов
и весов нод. Тестируем функцию восстановления напрямую (не HTTP-слой) — тот же
подход, что в test_address_context_builder.py и test_host_composition_snapshot.py.
"""

from __future__ import annotations

import sys
import types
from datetime import timedelta

# app/__init__.py тяжёлый, а app.subscription.share тянет за собой весь стек
# генерации ссылок — тот же обход, что в соседних тестах NPVPN-2072.
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
from app.db.crud import write_host_composition_snapshot  # noqa: E402
from app.db.models import Node, NodeWeightSnapshot, ProxyHost, ProxyInbound, User, UserNodePin  # noqa: E402
from app.services.address_history import day_start_at, reconstruct  # noqa: E402
from app.subscription.address_context import weighted_candidates  # noqa: E402
from app.xray.address_policy import pick_keys  # noqa: E402

if sys.modules.get("app.subscription.share") is _share_stub:
    del sys.modules["app.subscription.share"]

# rotation_days=1 делает epoch_start_day(user_id, day, 1) == day для любого юзера
# (сдвиг "размазки" внутри периода в один день не существует) — так тест не
# зависит от хеша смещения по юзеру.
BOT_SETTINGS = {"sub_address_subset_enabled": True, "sub_address_subset_size": 2, "sub_address_rotation_days": 1}

USER_ID = 1
DAY = 100


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _make_node(db, name: str, address: str, node_id: int | None = None) -> Node:
    node = Node(id=node_id, name=name, address=address, port=62050, api_port=62051)
    db.add(node)
    db.commit()
    db.refresh(node)
    return node


def _make_host(db, *, nodes: list[Node]) -> ProxyHost:
    inbound_tag = f"tag-{db.query(ProxyInbound).count()}"
    db.add(ProxyInbound(tag=inbound_tag))
    db.commit()
    host = ProxyHost(remark="host-remark", address="", inbound_tag=inbound_tag)
    host.nodes = nodes
    db.add(host)
    db.commit()
    db.refresh(host)
    return host


def _make_user(db, user_id: int = USER_ID) -> User:
    user = User(id=user_id, username=f"u{user_id}", address_rotation_offset=0)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_reconstructs_auto_assignment_from_snapshots(db):
    """Без пина ответ собирается хешем по снимкам весов и состава за те сутки."""
    _make_user(db)
    nodes = [_make_node(db, f"n{i}", f"1.2.3.{i}") for i in range(1, 5)]
    host = _make_host(db, nodes=nodes)

    payload = [{"node_id": n.id, "address": n.address} for n in nodes]
    write_host_composition_snapshot(db, DAY, host.id, payload)
    db.commit()

    weights = {nodes[0].id: 10.0, nodes[1].id: 20.0, nodes[2].id: 5.0, nodes[3].id: 1.0}
    for node_id, weight in weights.items():
        db.add(NodeWeightSnapshot(epoch_index=DAY, node_id=node_id, weight=weight))
    db.commit()

    result = reconstruct(db, USER_ID, DAY, BOT_SETTINGS)

    assert len(result) == 1
    assignment = result[0]
    assert assignment.host_id == host.id
    assert assignment.remark == "host-remark"
    assert assignment.source == "auto"
    assert assignment.restorable is True

    # Сверяем с реальным алгоритмом выдачи (тот же pick_keys/weighted_candidates,
    # что использует AddressContext.pick), а не с переизобретённой в тесте копией.
    node_ids = [n.id for n in nodes]
    candidates = list(weighted_candidates(weights, node_ids).items())
    expected_nodes = set(pick_keys(USER_ID, candidates, 2, DAY))
    assert set(assignment.node_ids) == expected_nodes
    assert len(assignment.addresses) == 2


def test_pin_wins_over_recomputation(db):
    """Пин, активный на ту дату, и есть ответ — пересчёт не применяется."""
    _make_user(db)
    nodes = [_make_node(db, f"n{i}", f"1.2.3.{i}") for i in range(1, 5)]
    host = _make_host(db, nodes=nodes)

    payload = [{"node_id": n.id, "address": n.address} for n in nodes]
    write_host_composition_snapshot(db, DAY, host.id, payload)
    db.commit()
    # Намеренно НЕТ снимка весов — если бы пин не выигрывал, auto-ветка
    # свалилась бы в "unknown". Пин обязан вернуть ответ без весов вовсе.

    pinned_node = nodes[2]
    db.add(
        UserNodePin(
            user_id=USER_ID,
            host_id=host.id,
            node_ids=[pinned_node.id],
            created_at=day_start_at(DAY),
            expires_at=day_start_at(DAY + 5),
            created_by="support",
        )
    )
    db.commit()

    result = reconstruct(db, USER_ID, DAY, BOT_SETTINGS)

    assert len(result) == 1
    assignment = result[0]
    assert assignment.source == "pin"
    assert assignment.restorable is True
    assert assignment.node_ids == [pinned_node.id]
    assert assignment.addresses == [pinned_node.address]


def test_expired_pin_does_not_affect_later_dates(db):
    """Истёкший пин виден в своей дате и не влияет на последующие."""
    _make_user(db)
    nodes = [_make_node(db, f"n{i}", f"1.2.3.{i}") for i in range(1, 3)]
    host = _make_host(db, nodes=nodes)

    payload = [{"node_id": n.id, "address": n.address} for n in nodes]
    # Состав неизменен оба дня.
    write_host_composition_snapshot(db, DAY, host.id, payload)
    write_host_composition_snapshot(db, DAY + 1, host.id, payload)
    db.commit()

    pinned_node = nodes[0]
    db.add(
        UserNodePin(
            user_id=USER_ID,
            host_id=host.id,
            node_ids=[pinned_node.id],
            created_at=day_start_at(DAY),
            expires_at=day_start_at(DAY + 1),  # истекает ровно на границе суток DAY -> DAY+1
            created_by="support",
        )
    )
    db.commit()

    on_pin_day = reconstruct(db, USER_ID, DAY, BOT_SETTINGS)
    assert on_pin_day[0].source == "pin"
    assert on_pin_day[0].node_ids == [pinned_node.id]

    # На DAY+1 адресов всего 2 <= size(2) — авто-ветке веса не нужны, поэтому
    # честно возвращается полный состав, а не "unknown".
    on_later_day = reconstruct(db, USER_ID, DAY + 1, BOT_SETTINGS)
    assert on_later_day[0].source == "auto"
    assert set(on_later_day[0].node_ids) == {n.id for n in nodes}


def test_missing_snapshot_reports_unknown_rather_than_guessing(db):
    """Снимка за дату нет — честно сообщаем, что восстановить нельзя, а не молчим
    пустым списком и не подсовываем правдоподобную догадку."""
    _make_user(db)
    nodes_a = [_make_node(db, f"a{i}", f"9.9.9.{i}") for i in range(1, 5)]
    host_missing_composition = _make_host(db, nodes=nodes_a)
    # Намеренно НЕ пишем снимок состава для этого хоста на DAY.

    nodes_b = [_make_node(db, f"b{i}", f"8.8.8.{i}") for i in range(1, 5)]
    host_missing_weights = _make_host(db, nodes=nodes_b)
    write_host_composition_snapshot(
        db, DAY, host_missing_weights.id, [{"node_id": n.id, "address": n.address} for n in nodes_b]
    )
    db.commit()
    # Состав есть, но снимка весов на DAY нет, а 4 адреса > size(2) — реальное
    # сужение было бы, угадывать веса нельзя.

    result = reconstruct(db, USER_ID, DAY, BOT_SETTINGS)
    by_host = {a.host_id: a for a in result}

    assert len(result) == 2  # оба хоста присутствуют в ответе, не пропущены молча

    missing_composition = by_host[host_missing_composition.id]
    assert missing_composition.source == "unknown"
    assert missing_composition.restorable is False
    assert missing_composition.node_ids == []
    assert missing_composition.addresses == []

    missing_weights = by_host[host_missing_weights.id]
    assert missing_weights.source == "unknown"
    assert missing_weights.restorable is False
    assert missing_weights.node_ids == []
    assert missing_weights.addresses == []


def test_day_start_at_roundtrips_with_day_index():
    from app.subscription.address_context_builder import day_index

    day = 42
    start = day_start_at(day)
    assert day_index(start) == day
    assert day_index(start + timedelta(hours=23, minutes=59)) == day
    assert day_index(start + timedelta(days=1)) == day + 1
