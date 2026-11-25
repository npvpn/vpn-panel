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


def test_saved_members_and_user_pin_resolve_same_static_source(db, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from app.db.models import Bot
    from app.services.address_history import location_members

    user = _make_user(db)
    own = _make_node(db, "04", "192.0.2.4")
    extra = _make_node(db, "07", "192.0.2.7")
    host = _make_host(db, nodes=[own])
    source = _make_host(db, nodes=[extra])
    source.address = extra.address
    source.is_hidden = True
    host.host_injection = {
        "addVirtualHostAsOutbound": True,
        "injectHosts": [{"selector": {"type": "ids", "values": [source.id]}, "tagPrefix": "proxy"}],
    }
    _grant_inbound_access(monkeypatch, db, user, [host, source])
    foreign = Bot(username="other_probe")
    host.bots.append(foreign)
    db.commit()
    tags = {host.inbound_tag, source.inbound_tag}
    loc = location_members(db, foreign.username, tags, set(), inspect_host_id=host.id)[0]
    assert [e.node_id for e in loc.entries] == [own.id]
    assert [e.source_host_id for e in loc.excluded_by_bot] == [source.id]
    loc = address_history.list_pinnable_hosts(db, user)[0]
    assert {(n.source_host_id, n.node_id) for n in loc.nodes} == {(host.id, own.id), (source.id, extra.id)}
    now = datetime.now(UTC)
    crud.create_user_node_pin(
        db,
        user_id=user.id,
        host_id=host.id,
        node_ids=[extra.id],
        tunnel_targets=[{"source_host_id": source.id, "node_id": extra.id}],
        expires_at=now + timedelta(hours=1),
        created_by="support",
        note=None,
    )
    targets = {}
    assert crud.get_active_pins(db, user.id, now, tunnel_pins=targets) == {}
    assert targets == {host.id: {(source.id, extra.id)}}
    targets = {}
    assert crud.get_active_pins(db, user.id, now + timedelta(hours=2), tunnel_pins=targets) == {}
    assert targets == {}


def test_composition_versions_are_audience_scoped_and_idempotent(db, monkeypatch):
    from datetime import datetime, timedelta

    from app.db.models import Bot, LocationMembership
    from app.services.location_history import refresh_membership

    user = _make_user(db)
    node = _make_node(db, "07", "192.0.2.7")
    source = _make_host(db, nodes=[node])
    source.is_hidden = True
    host = _make_host(db, nodes=[])
    host.host_injection = {"injectHosts": [{"selector": {"type": "ids", "values": [source.id]}, "tagPrefix": "proxy"}]}
    foreign = Bot(username="another_bot")
    host.bots.append(foreign)
    _grant_inbound_access(monkeypatch, db, user, [host, source])
    tags = {host.inbound_tag, source.inbound_tag}
    t0 = datetime(2026, 11, 22)
    refresh_membership(db, tags, now=t0)
    refresh_membership(db, tags, now=t0 + timedelta(hours=1))
    rows = db.query(LocationMembership).filter_by(host_id=host.id).all()
    assert [(r.bot_id, r.source_host_id, r.node_id, r.valid_until) for r in rows] == [
        (user.bot_id, source.id, node.id, None)
    ]
    source.bots = [foreign]
    db.commit()
    refresh_membership(db, tags, now=t0 + timedelta(days=1))
    assert db.query(LocationMembership).filter_by(
        host_id=host.id, bot_id=user.bot_id
    ).one().valid_until == t0 + timedelta(days=1)
    assert (
        db.query(LocationMembership).filter_by(host_id=host.id, bot_id=foreign.id, valid_until=None).one().node_id
        == node.id
    )

    from app.subscription.address_context_builder import day_index

    before = address_history.reconstruct(db, user.id, day_index(t0))
    location = next(item for item in before if item.host_id == host.id)
    assert (location.source, location.source_host_ids, location.node_ids) == ("pool", [source.id], [node.id])
    from app.db.models import UserNodePin

    db.add(
        UserNodePin(
            user_id=user.id,
            host_id=host.id,
            node_ids=[node.id],
            tunnel_targets=[{"source_host_id": source.id, "node_id": node.id}],
            created_by="support",
            created_at=t0,
            expires_at=t0 + timedelta(days=2),
        )
    )
    db.commit()
    assert (
        next(item for item in address_history.reconstruct(db, user.id, day_index(t0)) if item.host_id == host.id).source
        == "pin"
    )
    assert (
        next(
            item for item in address_history.reconstruct(db, user.id, day_index(t0) + 1) if item.host_id == host.id
        ).source
        == "unknown"
    )
