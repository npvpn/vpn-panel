"""Композиция не должна фальсифицировать историю и действующие закрепления."""

import json
from contextlib import contextmanager

import pytest

from app.db import crud
from app.db.models import HostCompositionSnapshot, XrayTemplate
from app.jobs import snapshot_host_composition as job
from app.services import address_history
from tests.test_address_history import DAY, _grant_inbound_access, _make_host, _make_node, _make_user, db  # noqa: F401


def setup(db, monkeypatch):
    user = _make_user(db)
    node = _make_node(db, "n1", "192.0.2.1")
    host = _make_host(db, nodes=[node], subset_enabled=False)
    _grant_inbound_access(monkeypatch, db, user, [host])
    return user, host


@pytest.mark.parametrize("via_template", [False, True])
def test_composite_not_pinnable_but_hidden_source_is(db, monkeypatch, via_template):
    user, host = setup(db, monkeypatch)
    host.is_hidden = True
    db.commit()
    assert len(address_history.list_pinnable_hosts(db, user)) == 1
    directive = {"addVirtualHostAsOutbound": True}
    if via_template:
        tpl = XrayTemplate(slug="default", title="Default")
        db.add(tpl)
        db.flush()
        from app.services.xray_templates import save_version

        save_version(db, tpl.id, json.dumps({"remnawave": directive}), None, None)
    else:
        host.host_injection = directive
    db.commit()
    assert address_history.list_pinnable_hosts(db, user) == []


@pytest.mark.parametrize("flag", ["is_hidden", "is_composite"])
def test_historical_flags_prevent_reconstruction_after_switch_back(db, monkeypatch, flag):
    user, host = setup(db, monkeypatch)
    crud.write_host_composition_snapshot(
        db, DAY, host.id, [{"node_id": None, "address": "real.example"}], **{flag: True}
    )
    db.commit()
    assert host.is_hidden is False and host.host_injection is None
    result = address_history.reconstruct(db, user.id, DAY)
    assert len(result) == 1 and result[0].source == "unknown" and not result[0].restorable


def test_job_records_empty_composite_and_hidden_marker(db, monkeypatch):
    _, host = setup(db, monkeypatch)
    host.host_injection = {"addVirtualHostAsOutbound": True}
    host.is_hidden = True
    db.commit()

    @contextmanager
    def get_db():
        yield db

    import app.db

    monkeypatch.setattr(app.db, "GetDB", get_db)
    monkeypatch.setattr(job, "GetDB", get_db)
    job.snapshot_host_composition()
    snap = db.query(HostCompositionSnapshot).filter_by(host_id=host.id).one()
    assert snap.payload == [] and snap.is_composite and snap.is_hidden


def test_current_hidden_does_not_claim_unmarked_history(db, monkeypatch):
    user, host = setup(db, monkeypatch)
    crud.write_host_composition_snapshot(db, DAY, host.id, [{"node_id": None, "address": "real.example"}])
    host.is_hidden = True
    db.commit()
    assert not address_history.reconstruct(db, user.id, DAY)[0].restorable
