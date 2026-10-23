"""Сохранение композиции без потери состояния старым API-клиентом."""

import json

import pytest

from tests.test_host_balancing_db import db, payload  # noqa: F401

# Bootstrap the DB harness before importing runtime-dependent modules.
# isort: split
from app.db import crud
from app.db.models import ProxyHost, ProxyInbound, XrayTemplate, XrayTemplateVersion
from app.models.proxy import ProxyHost as Payload
from app.services import xray_templates as service


def injection(ids):
    return {"injectHosts": [{"selector": {"type": "ids", "values": ids}, "tagPrefix": "proxy", "selectFrom": "ALL"}]}


def test_roundtrip_omitted_and_explicit_reset(db):
    source = crud.add_host(db, "VLESS", payload())[0]
    receiver = crud.add_host(
        db, "VLESS", payload(remark="Auto", host_injection=injection([source.id]), is_hidden=True, group_tag="MAIN")
    )[-1]
    view = Payload.model_validate(receiver)
    assert view.host_injection.injectHosts[0].selector.values == [source.id]
    assert view.is_hidden and view.group_tag == "MAIN"
    receiver_id = receiver.id
    crud.update_hosts(
        db, "VLESS", [Payload.model_validate(source), Payload(id=receiver.id, remark="Auto2", address="x")]
    )
    db.expire_all()
    receiver = db.get(ProxyHost, receiver_id)
    assert receiver.host_injection["injectHosts"][0]["selector"]["values"] == [source.id]
    assert receiver.is_hidden and receiver.group_tag == "MAIN"
    new = Payload.model_validate(receiver).model_copy(
        update={"host_injection": None, "is_hidden": False, "group_tag": ""}
    )
    crud.update_hosts(db, "VLESS", [Payload.model_validate(source), new])
    db.expire_all()
    assert receiver.host_injection is None and not receiver.is_hidden and receiver.group_tag == ""


def test_invalid_new_id_and_atomic_batch(db):
    source = crud.add_host(db, "VLESS", payload())[0]
    db.add(ProxyInbound(tag="OTHER"))
    db.commit()
    with pytest.raises(ValueError, match="host_injection"):
        crud.update_hosts_batch(
            db,
            {
                "VLESS": [Payload.model_validate(source).model_copy(update={"remark": "changed"})],
                "OTHER": [payload(host_injection=injection([9999]))],
            },
        )
    db.expire_all()
    assert db.get(ProxyHost, source.id).remark == "NL"


def test_deleted_source_reference_preserved_but_new_missing_rejected(db):
    source = crud.add_host(db, "VLESS", payload())[0]
    receiver = crud.add_host(db, "VLESS", payload(host_injection=injection([source.id])))[-1]
    receiver_id = receiver.id
    db.delete(source)
    db.commit()
    view = Payload.model_validate(db.get(ProxyHost, receiver_id))
    assert view.host_injection is not None
    crud.update_hosts(db, "VLESS", [view])
    with pytest.raises(ValueError, match="host_injection"):
        crud.update_hosts_batch(db, {"VLESS": [payload(id=receiver_id, host_injection=injection([999]))]})


def test_template_save_and_revert_validate_directives(db):
    tpl = XrayTemplate(slug="injected", title="Injected")
    db.add(tpl)
    db.commit()
    bad = json.dumps(
        {"npvpn": {"injectHosts": [{"selector": {"type": "uuids", "values": ["x"]}, "tagPrefix": "proxy"}]}}
    )
    with pytest.raises(service.InvalidTemplateBody):
        service.save_version(db, tpl.id, bad, None, None)
    db.add(XrayTemplateVersion(template_id=tpl.id, version=1, body=bad, author_username=""))
    db.commit()
    with pytest.raises(service.InvalidTemplateBody):
        service.revert(db, tpl.id, 1, None)
    valid = json.dumps({"npvpn": injection([123])})
    service.save_version(db, tpl.id, valid, None, None)
    assert service.get_active_bodies(db)["configs"][tpl.id] == valid


def test_migration_upgrade_downgrade_preserves_old_hosts():
    import importlib.util
    from pathlib import Path

    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = next((Path(__file__).parents[1] / "app/db/migrations/versions").glob("c45391e22595_*.py"))
    spec = importlib.util.spec_from_file_location("injection_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE hosts (id INTEGER PRIMARY KEY, remark TEXT)"))
        conn.execute(sa.text("INSERT INTO hosts VALUES (1, 'AU')"))
        conn.execute(sa.text("CREATE TABLE host_composition_snapshots (id INTEGER PRIMARY KEY, payload JSON)"))
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()
            row = conn.execute(sa.text("SELECT host_injection,group_tag,is_hidden FROM hosts")).one()
            assert tuple(row) == (None, "", 0)
            module.downgrade()
        assert [c["name"] for c in sa.inspect(conn).get_columns("hosts")] == ["id", "remark"]
        assert conn.execute(sa.text("SELECT remark FROM hosts")).scalar() == "AU"
