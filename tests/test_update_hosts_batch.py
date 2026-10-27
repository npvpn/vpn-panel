"""Перенос хостов сохраняет связи, порядок и атомарность PUT /hosts (NPVPN-2182)."""

from __future__ import annotations

import importlib.util
import sys
import types
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.exc import OperationalError, StatementError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

_saved_stubs = {}
for _name, _module in list(sys.modules.items()):
    if _name.startswith("app.") and not hasattr(_module, "__file__") and not hasattr(_module, "__path__"):
        _saved_stubs[_name] = sys.modules.pop(_name)
_share_stub = types.ModuleType("app.subscription.share")
_share_stub.generate_v2ray_links = lambda *_args, **_kwargs: []
sys.modules.setdefault("app.subscription.share", _share_stub)

from app.db import crud
from app.db.base import Base
from app.db.models import Bot, Node, ProxyHost, ProxyInbound, User, UserNodePin, host_bot_association
from app.models.proxy import ProxyHost as Payload
from app.models.proxy import ProxyHostALPN, ProxyHostFingerprint

if sys.modules.get("app.subscription.share") is _share_stub:
    del sys.modules["app.subscription.share"]
sys.modules.update(_saved_stubs)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def enable_fk(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    # Проверяем связи без автоматического expire, который маскировал бы их рассинхрон.
    with Session(engine, expire_on_commit=False) as session:
        yield session
    engine.dispose()


@pytest.fixture
def catalog(db):
    source, destination = ProxyInbound(tag="SOURCE"), ProxyInbound(tag="DEST")
    rented, service = Bot(username="rented"), Bot(username="service")
    node = Node(name="node", address="192.0.2.1", port=62050, api_port=62051)
    moving = ProxyHost(
        inbound=source,
        remark="Moving",
        address="edge.example",
        order=7,
        bots=[rented, service],
        nodes=[node],
        port=443,
        sni="sni.example",
        host="host.example",
        path="/path",
        alpn=ProxyHostALPN.none,
        fingerprint="chrome",
        xhttp_extra={"headers": {"X-Test": "value"}},
    )
    staying = ProxyHost(
        inbound=source,
        remark="Staying",
        address="stay.example",
        order=8,
        alpn=ProxyHostALPN.none,
        fingerprint=ProxyHostFingerprint.none,
    )
    anchor = ProxyHost(
        inbound=destination,
        remark="Anchor",
        address="anchor.example",
        order=100,
        alpn=ProxyHostALPN.none,
        fingerprint=ProxyHostFingerprint.none,
    )
    db.add_all([source, destination, moving, staying, anchor])
    db.flush()
    user = User(username="pinned", bot=rented)
    db.add(user)
    db.flush()
    pin = UserNodePin(
        user_id=user.id,
        host_id=moving.id,
        node_ids=[node.id],
        expires_at=datetime(2030, 1, 1),
        created_by="support",
    )
    db.add(pin)
    db.execute(
        host_bot_association.update()
        .where(host_bot_association.c.host_id == moving.id, host_bot_association.c.bot_id == rented.id)
        .values(rented_at=datetime(2026, 10, 1))
    )
    db.commit()
    return types.SimpleNamespace(
        source=source, destination=destination, moving=moving, staying=staying, anchor=anchor, node=node, pin=pin
    )


def payload(host, **changes):
    return Payload.model_validate(host).model_copy(update=changes)


def rental_rows(db, host_id):
    rows = db.execute(host_bot_association.select().where(host_bot_association.c.host_id == host_id)).all()
    return {row.bot_id: row.rented_at for row in rows}


@pytest.mark.parametrize("source_first", [True, False])
def test_move_preserves_identity_settings_and_associations(db, catalog, source_first):
    """Удаление/пересоздание при переносе теряет пины и исходную дату аренды."""
    host_id, pin_id = catalog.moving.id, catalog.pin.id
    before = payload(catalog.moving).model_dump()
    rents = rental_rows(db, host_id)
    entries = [("SOURCE", [payload(catalog.staying)]), ("DEST", [payload(catalog.moving), payload(catalog.anchor)])]
    request = dict(entries if source_first else reversed(entries))

    crud.update_hosts_batch(db, request)
    crud.update_hosts_batch(db, request)

    db.expire_all()
    moved = db.get(ProxyHost, host_id)
    assert moved.inbound_tag == "DEST"
    assert payload(moved).model_dump() == before
    assert rental_rows(db, host_id) == rents
    assert sorted(bot.username for bot in moved.bots) == ["rented", "service"]
    assert len(rents) == 2 and set(rents.values()) == {None, datetime(2026, 10, 1)}
    assert moved.node_ids == [catalog.node.id]
    assert db.get(UserNodePin, pin_id).host_id == host_id
    assert db.get(UserNodePin, pin_id).node_ids == [catalog.node.id]
    assert db.query(ProxyHost).count() == 3


@pytest.mark.parametrize("order", [None, 0, 42])
def test_move_preserves_order_when_omitted_and_accepts_explicit_order(db, catalog, order):
    """Отсутствующий order не должен пересортировать переносимый хост."""
    incoming = payload(catalog.moving).model_dump(exclude={"order"})
    if order is not None:
        incoming["order"] = order
    data = Payload.model_validate(incoming)
    crud.update_hosts_batch(db, {"SOURCE": [payload(catalog.staying)], "DEST": [data, payload(catalog.anchor)]})

    assert db.get(ProxyHost, catalog.moving.id).order == (7 if order is None else order)
    assert data.order == order  # Сервер не меняет модель запроса при заполнении order.


def test_repeat_move_without_order_keeps_position(db, catalog):
    """Повтор того же запроса после успешного переноса не меняет сортировку."""
    request = {
        "SOURCE": [payload(catalog.staying)],
        "DEST": [payload(catalog.moving, order=None), payload(catalog.anchor)],
    }
    crud.update_hosts_batch(db, request)
    assert db.get(ProxyHost, catalog.moving.id).order == 7

    crud.update_hosts_batch(db, request)

    assert db.get(ProxyHost, catalog.moving.id).order == 7


def test_move_from_omitted_inbound_keeps_neighbours_and_loaded_relationships(db, catalog):
    """Перенос не очищает пропущенный inbound и обновляет обе стороны ORM-связи."""
    assert catalog.moving.inbound is catalog.source
    assert set(catalog.source.hosts) == {catalog.moving, catalog.staying}
    assert catalog.destination.hosts == [catalog.anchor]

    crud.update_hosts_batch(db, {"DEST": [payload(catalog.moving), payload(catalog.anchor)]})

    assert catalog.moving.inbound is catalog.destination
    assert catalog.source.hosts == [catalog.staying]
    assert set(catalog.destination.hosts) == {catalog.moving, catalog.anchor}
    assert db.get(ProxyHost, catalog.staying.id).inbound_tag == "SOURCE"


@pytest.mark.parametrize("source_position", ["first", "last", "omitted"])
def test_move_with_loaded_source_collection_and_unloaded_parent_keeps_host_and_pin(db, catalog, source_position):
    """Коллекция source без загруженной host.inbound не должна удалять переносимый ID."""
    moving_id, staying_id, source_id, pin_id = catalog.moving.id, catalog.staying.id, catalog.source.id, catalog.pin.id
    entries = [("SOURCE", [payload(catalog.staying)]), ("DEST", [payload(catalog.moving), payload(catalog.anchor)])]
    request = dict(entries if source_position == "first" else reversed(entries))
    if source_position == "omitted":
        del request["SOURCE"]
    db.expunge_all()
    source = db.get(ProxyInbound, source_id)
    loaded = {host.id: host for host in source.hosts}
    # Состояние, которое не создаёт seeded fixture: коллекция прочитана из БД,
    # но обратная many-to-one связь ещё не прочитана.
    assert "inbound" in inspect(loaded[moving_id]).unloaded

    crud.update_hosts_batch(db, request)

    assert [host.id for host in source.hosts] == [staying_id]
    db.expire_all()
    assert db.get(ProxyHost, moving_id).inbound_tag == "DEST"
    assert db.get(UserNodePin, pin_id).host_id == moving_id
    assert db.query(ProxyHost).count() == 3


def test_swap_hosts_in_one_request(db, catalog):
    """Два встречных переноса не должны удалять друг друга."""
    crud.update_hosts_batch(
        db,
        {"SOURCE": [payload(catalog.anchor), payload(catalog.staying)], "DEST": [payload(catalog.moving)]},
    )
    db.expire_all()
    assert db.get(ProxyHost, catalog.anchor.id).inbound_tag == "SOURCE"
    assert db.get(ProxyHost, catalog.moving.id).inbound_tag == "DEST"
    assert db.query(ProxyHost).count() == 3
    assert db.query(UserNodePin).one().host_id == catalog.moving.id


def test_create_move_and_delete_in_one_request(db, catalog):
    """Новый inbound не получает лишний default host, удаление сохраняет каскад."""
    moving_id, staying_id, anchor_id = catalog.moving.id, catalog.staying.id, catalog.anchor.id
    crud.update_hosts_batch(
        db,
        {"SOURCE": [], "NEW": [payload(catalog.moving), Payload(remark="New", address="new.example")]},
    )
    assert db.get(ProxyHost, moving_id).inbound_tag == "NEW"
    assert db.get(ProxyHost, staying_id) is None
    assert db.get(ProxyHost, anchor_id).inbound_tag == "DEST"
    assert {host.remark for host in crud.get_hosts(db, "NEW")} == {"Moving", "New"}
    assert db.query(UserNodePin).count() == 1

    crud.update_hosts_batch(db, {"NEW": []})
    assert db.get(ProxyHost, moving_id) is None
    assert db.query(UserNodePin).count() == 0
    assert rental_rows(db, moving_id) == {}


@pytest.mark.parametrize("invalid", ["unknown", "duplicate_same", "duplicate_across"])
def test_invalid_ids_rejected_without_partial_changes(db, catalog, invalid):
    """Некорректный ID не приводит к созданию inbound или частичному сохранению."""
    data = payload(catalog.moving)
    if invalid == "unknown":
        bad = {"NEW": [data.model_copy(update={"id": 999999})]}
    elif invalid == "duplicate_same":
        bad = {"NEW": [data, data]}
    else:
        bad = {"SOURCE": [data], "NEW": [data]}
    with pytest.raises(ValueError):
        crud.update_hosts_batch(db, bad)

    assert db.query(ProxyHost).count() == 3
    assert db.query(ProxyInbound).filter_by(tag="NEW").count() == 0
    assert db.get(ProxyHost, catalog.moving.id).inbound_tag == "SOURCE"
    assert db.query(UserNodePin).count() == 1


@pytest.mark.parametrize("failure", ["node", "rental", "flush", "commit"])
def test_late_failure_rolls_back_moves_updates_creates_and_deletes(db, catalog, failure):
    """Ошибка после обработки первого inbound откатывает всё, включая удаление."""
    ids = catalog.moving.id, catalog.staying.id, catalog.anchor.id
    rents = rental_rows(db, ids[0])
    second = payload(catalog.moving)
    if failure == "node":
        second.node_ids = [999999]
    elif failure == "rental":
        second.rented_bot_usernames = ["unbound"]
    elif failure == "flush":
        # JSON-колонка отклонит не сериализуемое значение при flush/commit.
        second.xhttp_extra = {"bad": object()}
    else:

        @event.listens_for(db, "before_commit", once=True)
        def fail_commit(_session):
            raise OperationalError("COMMIT", {}, RuntimeError("commit failed"))

    expected_error = {"flush": StatementError, "commit": OperationalError}.get(failure, ValueError)
    with pytest.raises(expected_error):
        crud.update_hosts_batch(
            db,
            {
                "DEST": [payload(catalog.anchor, remark="Changed"), Payload(remark="New", address="new.example")],
                "SOURCE": [],
                "NEW": [second],
            },
        )

    assert db.query(ProxyHost).count() == 3
    assert db.get(ProxyHost, ids[0]).inbound_tag == "SOURCE"
    assert db.get(ProxyHost, ids[1]).remark == "Staying"
    assert db.get(ProxyHost, ids[2]).remark == "Anchor"
    assert db.query(ProxyInbound).filter_by(tag="NEW").count() == 0
    assert rental_rows(db, ids[0]) == rents
    assert db.query(UserNodePin).one().host_id == ids[0]


@pytest.fixture
def api(db, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    monkeypatch.setattr(sys.modules["app"], "__version__", "test", raising=False)
    spec = importlib.util.spec_from_file_location(
        "hosts_batch_system", Path(__file__).parents[1] / "app/routers/system.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(
        module.xray, "config", types.SimpleNamespace(inbounds_by_tag={"SOURCE": {}, "DEST": {}}), raising=False
    )
    cached = []
    monkeypatch.setattr(module.xray, "hosts", types.SimpleNamespace(update=lambda: cached.append(True)), raising=False)
    app = FastAPI()
    app.include_router(module.router)
    app.dependency_overrides[module.get_db] = lambda: db
    app.dependency_overrides[module.Admin.check_sudo_admin] = lambda: module.Admin(username="sudo", is_sudo=True)
    with TestClient(app) as client:
        yield client, cached


def test_http_move_uses_existing_payload_and_returns_new_inbound(api, db, catalog):
    """Настоящий PUT переносит ID и возвращает хост под новым inbound."""
    client, cached = api
    response = client.put(
        "/api/hosts",
        json={
            "SOURCE": [payload(catalog.staying).model_dump(mode="json")],
            "DEST": [payload(catalog.moving).model_dump(mode="json"), payload(catalog.anchor).model_dump(mode="json")],
        },
    )
    assert response.status_code == 200, response.text
    assert [host["id"] for host in response.json()["SOURCE"]] == [catalog.staying.id]
    assert [host["id"] for host in response.json()["DEST"]] == [catalog.moving.id, catalog.anchor.id]
    assert response.json()["DEST"][0]["rented_bot_usernames"] == ["rented"]
    assert db.query(UserNodePin).one().host_id == catalog.moving.id
    assert cached == [True]


@pytest.mark.parametrize("failure", ["duplicate", "unknown", "node", "inbound", "client_config"])
def test_http_invalid_batch_keeps_database_and_cache(api, db, catalog, failure):
    """HTTP-ошибка не публикует частичное состояние в БД/кэш."""
    client, cached = api
    data = payload(catalog.moving).model_dump(mode="json")
    second = {"DEST": [data, payload(catalog.anchor).model_dump(mode="json")]}
    if failure == "duplicate":
        second = {"DEST": [data, data]}
    elif failure == "unknown":
        data["id"] = 999999
    elif failure == "node":
        data["node_ids"] = [999999]
    elif failure == "inbound":
        second = {"MISSING": [data]}
    else:
        data["client_config_id"] = 999999
    response = client.put("/api/hosts", json={"SOURCE": [], **second})

    assert response.status_code == (422 if failure == "client_config" else 400), response.text
    assert db.query(ProxyHost).count() == 3
    assert db.get(ProxyHost, catalog.moving.id).inbound_tag == "SOURCE"
    assert db.query(UserNodePin).count() == 1
    assert cached == []
