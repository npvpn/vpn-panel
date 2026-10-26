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


def test_preview_drafts_do_not_write_or_resurrect_deleted_hosts(db):
    from app.models.host_injection import InjectionPreviewRequest

    source = crud.add_host(db, "VLESS", payload(is_disabled=True))[0]
    source.is_disabled = True
    db.commit()
    request = InjectionPreviewRequest.model_validate(
        {
            "recipient": {"host_injection": injection([source.id, 999])},
            "hosts": [
                {"id": source.id, "inbound_tag": "VLESS", "is_disabled": False},
                {"id": 999, "inbound_tag": "VLESS"},
            ],
        }
    )
    result = service.preview_injection(db, request, {"VLESS"})
    assert result.groups[0].host_ids == [source.id]
    assert any(i.code == "missing_source" and i.host_id == 999 for i in result.issues)
    db.expire_all()
    assert db.get(ProxyHost, source.id).is_disabled
    assert db.get(ProxyHost, 999) is None


def test_preview_json_draft_uses_fallback_without_mutating_cache(db, monkeypatch):
    from app.models.host_injection import InjectionPreviewRequest

    source = crud.add_host(db, "VLESS", payload(host_injection={"enabled": False}))[0]
    tpl = XrayTemplate(slug="default", title="default")
    db.add(tpl)
    db.commit()
    service.save_version(db, tpl.id, json.dumps({"npvpn": injection([source.id])}), None, None)
    request = InjectionPreviewRequest.model_validate(
        {
            "recipient": {"client_config_id": tpl.id},
            "template_body": '{"npvpn":{"injectHosts":[{"selector":{"type":"tagRegex","pattern":"TYPO"},"tagPrefix":"proxy"}]}}',
        }
    )
    result = service.preview_injection(db, request, {"VLESS"})
    assert any(i.code == "empty_injection" for i in result.issues)
    assert "TYPO" not in service.get_active_bodies(db)["configs"][tpl.id]
    request.template_body = None
    assert service.preview_injection(db, request, {"VLESS"}).groups[0].host_ids == [source.id]
    import importlib

    monkeypatch.setattr(
        importlib.import_module("app.templates"),
        "render_template",
        lambda _: json.dumps({"npvpn": injection([source.id])}),
    )
    request.template_body = ""
    assert service.preview_injection(db, request, {"VLESS"}).groups[0].host_ids == [source.id]
    request.template_body = "{"
    assert service.preview_injection(db, request, {"VLESS"}).issues[0].code == "invalid_template"


def test_preview_removes_draft_deleted_source_without_deleting_db_row(db):
    from app.models.host_injection import InjectionPreviewRequest

    source = crud.add_host(db, "VLESS", payload())[0]
    request = InjectionPreviewRequest.model_validate(
        {
            "recipient": {"host_injection": injection([source.id])},
            "excluded_host_ids": [source.id],
        }
    )
    result = service.preview_injection(db, request, {"VLESS"})
    assert result.groups[0].host_ids == []
    assert any(i.code == "missing_source" and i.host_id == source.id for i in result.issues)
    assert db.get(ProxyHost, source.id) is not None
    request.excluded_host_ids = []
    assert service.preview_injection(db, request, {"VLESS"}).groups[0].host_ids == [source.id]


def test_preview_api_sudo_gate_and_response_schema(monkeypatch):
    import importlib.util
    import pathlib
    import sys
    import types

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.models.admin import Admin
    from app.models.host_injection import InjectionDiagnostic, InjectionGroupPreview, InjectionPreview

    monkeypatch.setattr(sys.modules["app"], "__version__", "test", raising=False)
    spec = importlib.util.spec_from_file_location(
        "preview_system_router", pathlib.Path(__file__).parents[1] / "app/routers/system.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    api = FastAPI()
    api.include_router(module.router)
    api.dependency_overrides[module.get_db] = lambda: None
    monkeypatch.setattr(module.xray, "config", types.SimpleNamespace(inbounds_by_tag={"VLESS": {}}), raising=False)
    calls = []

    def preview_stub(db, request, inbounds):
        calls.append((request, inbounds))
        return InjectionPreview(
            active=True,
            groups=[InjectionGroupPreview(group=1)],
            issues=[InjectionDiagnostic(code="empty_injection", level="error")],
        )

    monkeypatch.setattr(service, "preview_injection", preview_stub)
    monkeypatch.setattr(Admin, "get_admin", lambda *a: types.SimpleNamespace(is_sudo=False))
    client = TestClient(api)
    payload = {"recipient": {"host_injection": injection([1])}}
    assert client.post("/api/hosts/injection/preview", json=payload).status_code == 401
    assert (
        client.post("/api/hosts/injection/preview", json=payload, headers={"Authorization": "Bearer test"}).status_code
        == 403
    )
    assert calls == []
    monkeypatch.setattr(Admin, "get_admin", lambda *a: types.SimpleNamespace(is_sudo=True))
    response = client.post("/api/hosts/injection/preview", json=payload, headers={"Authorization": "Bearer test"})
    assert response.status_code == 200
    assert response.json()["groups"][0]["host_ids"] == []
    assert response.json()["issues"][0]["code"] == "empty_injection"
    assert calls[0][1] == {"VLESS"}


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
