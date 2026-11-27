import sys
import types
from uuid import uuid4

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def pilot(monkeypatch, tmp_path):
    share = types.ModuleType("app.subscription.share")
    share.generate_v2ray_links = lambda *_args, **_kwargs: []
    with monkeypatch.context() as patch:
        patch.setitem(sys.modules, "app.subscription.share", share)
        from app.db.models import Base, Node, ProxyInbound
        from app.services import haproxy_pilot as service
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'panel.sqlite3'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    with factory.begin() as db:
        db.add_all(
            [
                Node(
                    id=i,
                    address=f"node{i}",
                    name=f"node{i}",
                    port=1234,
                    api_port=1235,
                    status="connected",
                    control_session_id="session",
                )
                for i in (1, 2)
            ]
        )
        db.add(ProxyInbound(tag="vpn"))
    state = dict(
        revision=0,
        target=None,
        enabled=False,
        listen_address="127.0.0.1",
        listen_port=1111,
        targets={"a": dict(address="127.0.0.2", port=2222, exit_node_id=2, inbound_tag="vpn")},
        listener="down",
        backend="unknown",
    )
    calls = []
    results = {}
    failures = {}

    def rpc(path, **body):
        calls.append(path)
        if path in failures:
            fail = failures[path]
            if callable(fail):
                return fail(**body)
            raise service.NodeAPIError(fail, "failure")
        if path == "/":
            return {"capabilities": {"haproxy_pilot": 1}}
        if path.endswith("/status"):
            return state.copy()
        if path.endswith("/validate"):
            return {"valid": True, "revision": state["revision"]}
        key = body["operation_id"]
        if path.endswith("/result"):
            if key not in results:
                raise service.NodeAPIError(404, "unknown")
            return results[key]
        assert path.endswith("/apply")
        with factory() as db:
            saved = db.get(service.PilotOperation, key)
            assert saved.operator == "operator" and saved.outcome == "pending" and saved.exit_node_id == 2
        assert state["revision"] == body["expected_revision"]
        state.update(revision=state["revision"] + 1, target=body["target"], enabled=body["enabled"])
        results[key] = dict(operation_id=key, outcome="applied", revision=state["revision"], detail="ok")
        return results[key]

    node = object.__new__(service.ReSTXRayNode)
    node.address, node.port, node.api_port = "node1", 1234, 1235
    node._session_id, node._node_cert = "session", "peer"
    monkeypatch.setattr(service.xray, "nodes", {1: node}, raising=False)
    monkeypatch.setattr(node, "pilot_request", lambda session_id, path, **data: rpc(path, **data))
    svc = service.PilotService(factory, 1)
    req = service.PilotCommand(operation_id=uuid4(), expected_revision=0, target="a", enabled=True)
    return svc, req, state, calls, failures, results, factory


def test_apply_is_durable_and_replay_is_idempotent(pilot):
    svc, req, state, calls, *_ = pilot
    view = svc.apply(req, "operator")
    assert view.state.revision == 1
    assert view.history[0].operation_id == req.operation_id
    assert view.history[0].outcome == "applied"
    assert svc.apply(req, "operator").history == view.history
    assert calls.count("/haproxy-pilot/apply") == 1
    with pytest.raises(HTTPException) as error:
        svc.apply(req.model_copy(update={"enabled": False}), "operator")
    assert error.value.status_code == 409


def test_lost_reply_pending_read_then_retry(pilot):
    svc, req, state, calls, failures, *_ = pilot
    failures["/haproxy-pilot/apply"] = 0
    assert svc.apply(req, "operator").history[0].outcome == "pending"
    assert svc.status().history[0].outcome == "pending"
    with pytest.raises(HTTPException) as error:
        svc.apply(req.model_copy(update={"operation_id": uuid4()}), "operator")
    assert error.value.status_code == 409
    failures.clear()
    assert svc.apply(req, "operator").history[0].outcome == "applied"
    assert calls.count("/haproxy-pilot/result") >= 2


def test_malformed_result_cannot_confirm_intent(pilot):
    svc, req, state, calls, failures, results, _ = pilot
    failures["/haproxy-pilot/apply"] = lambda **_: dict(
        operation_id=str(uuid4()), outcome="applied", revision=99, detail="wrong"
    )
    assert svc.apply(req, "operator").history[0].outcome == "pending"
    results[str(req.operation_id)] = dict(
        operation_id=str(req.operation_id), outcome="applied", revision=1, detail="ok"
    )
    state.update(revision=1, target="a", enabled=True)
    assert svc.status().history[0].outcome == "applied"
    assert calls.count("/haproxy-pilot/apply") == 1


def test_stale_state_or_unknown_binding_prevents_dispatch(pilot):
    svc, req, state, calls, _, _, _ = pilot
    state["targets"]["a"]["exit_node_id"] = 987
    with pytest.raises(HTTPException) as error:
        svc.apply(req, "operator")
    assert error.value.status_code == 409
    assert "/haproxy-pilot/apply" not in calls


def test_concurrent_distinct_intents_share_a_single_slot(pilot):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    svc, req, state, calls, failures, results, _ = pilot
    entered, release = Event(), Event()

    def pause(**body):
        entered.set()
        assert release.wait(5)
        return dict(operation_id=body["operation_id"], outcome="pending", revision=None, detail="running")

    failures["/haproxy-pilot/apply"] = pause
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(svc.apply, req, "operator")
        try:
            assert entered.wait(5)
            with pytest.raises(HTTPException) as error:
                svc.apply(req.model_copy(update={"operation_id": uuid4()}), "operator")
            assert error.value.status_code == 409
        finally:
            release.set()
        assert first.result().history[0].outcome == "pending"
    assert calls.count("/haproxy-pilot/apply") == 1


def test_existing_result_wins_over_late_pending_reply(pilot):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    svc, req, state, calls, failures, results, _ = pilot
    entered, release = Event(), Event()

    def pause(**body):
        key = body["operation_id"]
        state.update(revision=1, target="a", enabled=True)
        results[key] = dict(operation_id=key, outcome="applied", revision=1, detail="ok")
        entered.set()
        assert release.wait(5)
        return dict(operation_id=key, outcome="pending", revision=None, detail="delayed")

    failures["/haproxy-pilot/apply"] = pause
    with ThreadPoolExecutor(1) as pool:
        first = pool.submit(svc.apply, req, "operator")
        try:
            assert entered.wait(5)
            assert svc.status().history[0].outcome == "applied"
        finally:
            release.set()
        assert first.result().history[0].outcome == "applied"


@pytest.mark.parametrize(
    "kind",
    ["rpyc", "legacy", "unsupported version", "missing session", "wrong session", "other address", "pending edit"],
)
def test_unsupported_or_uncertain_node_never_receives_commands(pilot, kind):
    from app.services import haproxy_pilot as service

    svc, req, state, calls, failures, _, factory = pilot
    with factory.begin() as db:
        node = db.get(service.Node, 1)
        if kind == "rpyc":
            node.protocol = "rpyc"
        elif kind == "pending edit":
            node.config_apply_pending = True
        elif kind == "missing session":
            node.control_session_id = None
        elif kind == "wrong session":
            node.control_session_id = "expired"
        elif kind == "other address":
            node.address = "other"
        elif kind == "legacy":
            failures["/"] = lambda: {}
        elif kind == "unsupported version":
            failures["/"] = lambda: {"capabilities": {"haproxy_pilot": True}}
    if kind in ("rpyc", "legacy", "unsupported version"):
        assert svc.status().supported is False
    with pytest.raises(HTTPException) as error:
        svc.apply(req, "operator")
    assert error.value.status_code in (409, 503)
    assert all(path == "/" for path in calls)


def test_endpoint_replacement_never_receives_an_old_intent(pilot):
    from app.services import haproxy_pilot as service

    svc, req, state, calls, failures, _, _ = pilot
    failures["/haproxy-pilot/apply"] = 403
    assert svc.apply(req, "operator").history[0].outcome == "pending"
    service.xray.nodes[1]._node_cert = "different"
    failures.clear()
    assert svc.apply(req, "operator").state is None
    assert calls.count("/haproxy-pilot/apply") == 1
    assert "/haproxy-pilot/result" not in calls


def test_transport_uses_active_session_certificate_and_refuses_redirects(monkeypatch):
    from unittest.mock import Mock

    from app.xray.node import NodeAPIError, ReSTXRayNode

    node = object.__new__(ReSTXRayNode)
    node._rest_api_url = "https://example.test"
    node._node_certfile = types.SimpleNamespace(name="/known-peer-cert")
    node._session_id = "current"
    node.session = Mock()
    node.session.post.return_value.status_code = 403
    node.session.post.return_value.json.return_value = {"detail": "invalid session"}
    with pytest.raises(NodeAPIError) as e:
        node.pilot_request("current", "/haproxy-pilot/status")
    assert e.value.status_code == 403
    call = node.session.post.call_args
    assert call.kwargs["json"] == {"session_id": "current"}
    assert call.kwargs["verify"] == "/known-peer-cert"
    assert call.kwargs["allow_redirects"] is False
    assert node._session_id == "current"
    with pytest.raises(NodeAPIError):
        node.pilot_request("old", "/haproxy-pilot/status")
    assert node.session.post.call_count == 1


def test_sudo_endpoints_and_contract(pilot, monkeypatch):
    import importlib.util
    from pathlib import Path

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.models.admin import Admin

    svc, req, _, calls, _, _, factory = pilot
    spec = importlib.util.spec_from_file_location(
        "pilot_api_routes", Path(__file__).parents[1] / "app/routers/haproxy_pilot.py"
    )
    route = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(route)
    app = FastAPI()
    app.include_router(route.router)
    monkeypatch.setattr(route, "SessionLocal", factory)

    def db_dep():
        with factory() as db:
            yield db

    app.dependency_overrides[route.get_db] = db_dep
    monkeypatch.setattr(Admin, "get_admin", lambda token, db: Admin(username="operator", is_sudo=token == "sudo"))
    client = TestClient(app)
    path = "/api/node/1/haproxy-pilot"
    data = req.model_dump(mode="json")
    for method, kwargs in [(client.get, {}), (client.post, {"json": data})]:
        assert method(path, **kwargs).status_code == 401
        assert method(path, headers={"Authorization": "Bearer user"}, **kwargs).status_code == 403
    assert calls == []
    headers = {"Authorization": "Bearer sudo"}
    assert client.get(path, headers=headers).json()["state"]["revision"] == 0
    assert client.post(path, headers=headers, json={**data, "enabled": "False"}).status_code == 422
    response = client.post(path, headers=headers, json=data)
    assert response.status_code == 200, response.text
    view = response.json()
    assert set(view) == {"history", "state", "supported"}
    assert view["history"][0]["operator"] == "operator"
    assert view["history"][0]["outcome"] == "applied"


def test_stale_audit_fences_an_unknown_operation_on_refresh(pilot):
    svc, req, state, calls, failures, _, _ = pilot
    failures["/haproxy-pilot/apply"] = 0
    assert svc.apply(req, "operator").history[0].outcome == "pending"
    state.update(revision=1, target="a", enabled=True)
    failures.clear()
    assert svc.status().history[0].outcome == "rejected"
    assert calls.count("/haproxy-pilot/apply") == 1


def test_confirmed_binding_does_not_change_with_the_policy(pilot):
    svc, req, state, calls, failures, _, _ = pilot
    assert svc.apply(req, "operator").history[0].outcome == "applied"
    previous = state["targets"]["a"].copy()
    state["targets"]["a"]["port"] = 9876
    with pytest.raises(HTTPException) as exc:
        svc.status()
    assert exc.value.status_code == 503
    state["confirmed_destination"] = previous
    assert svc.status().state.confirmed_destination.port == 2222


@pytest.mark.parametrize("removed", [True, False])
def test_pending_retry_sends_original_binding_after_policy_change(pilot, removed):
    svc, req, state, calls, failures, results, factory = pilot
    original = state["targets"]["a"].copy()
    failures["/haproxy-pilot/apply"] = 0
    assert svc.apply(req, "operator").history[0].outcome == "pending"
    if removed:
        del state["targets"]["a"]
    else:
        state["targets"]["a"]["address"] = "new-target"

    def reject(**command):
        assert command["expected_destination"] == original
        assert command["target"] == "a"
        key = command["operation_id"]
        assert key == str(req.operation_id)
        results[key] = dict(operation_id=key, outcome="rejected", revision=0, detail="Target policy changed")
        return results[key]

    failures["/haproxy-pilot/apply"] = reject
    assert svc.apply(req, "operator").history[0].outcome == "rejected"
    assert svc.apply(req, "operator").history[0].outcome == "rejected"
    assert calls.count("/haproxy-pilot/apply") == 2
    state["targets"]["new"] = original
    del failures["/haproxy-pilot/apply"]
    next_command = req.model_copy(update={"operation_id": uuid4(), "target": "new"})
    assert svc.apply(next_command, "operator").history[0].outcome == "applied"


@pytest.mark.parametrize("changed", ["removed", "remapped", "disabled exit", "deleted inbound"])
def test_disable_current_uses_confirmed_destination_even_after_catalog_changes(pilot, changed):
    from app.services import haproxy_pilot as service

    svc, command, state, calls, failures, results, sessions = pilot
    assert svc.apply(command, "operator").state.enabled
    original = state["targets"]["a"].copy()
    state["confirmed_destination"] = original
    match changed:
        case "removed":
            del state["targets"]["a"]
        case "remapped":
            state["targets"]["a"]["address"] = "different"
        case "disabled exit":
            with sessions.begin() as db:
                db.get(service.Node, 2).status = "disabled"
        case "deleted inbound":
            with sessions.begin() as db:
                db.query(service.ProxyInbound).delete()

    def disable(**body):
        assert body["expected_destination"] == original
        state.update(enabled=False, revision=2, listener="down")
        key = body["operation_id"]
        results[key] = dict(operation_id=key, outcome="applied", revision=2, detail="closed")
        return results[key]

    failures["/haproxy-pilot/apply"] = disable
    stop = command.model_copy(update={"operation_id": uuid4(), "enabled": False, "expected_revision": 1})
    assert svc.apply(stop, "operator").history[0].outcome == "applied"


def test_panel_rejects_snapshot_seen_before_remap(pilot):
    svc, req, state, calls, _, _, _ = pilot
    candidate = req.model_validate({**req.model_dump(), "expected_destination": state["targets"]["a"]})
    state["targets"]["a"]["port"] += 1
    with pytest.raises(HTTPException) as conflict:
        svc.apply(candidate, "operator")
    assert conflict.value.status_code == 409
    assert not svc.status().history
    assert "/haproxy-pilot/apply" not in calls


def test_replay_must_match_persisted_operator_snapshot(pilot):
    svc, req, state, calls, _, _, _ = pilot
    original = req.model_validate({**req.model_dump(), "expected_destination": state["targets"]["a"]})
    assert svc.apply(original, "operator").history[0].outcome == "applied"
    assert svc.apply(original, "operator").history[0].outcome == "applied"
    other = req.model_validate({**req.model_dump(), "expected_destination": {**state["targets"]["a"], "port": 9876}})
    with pytest.raises(HTTPException) as conflict:
        svc.apply(other, "operator")
    assert conflict.value.status_code == 409
    assert calls.count("/haproxy-pilot/apply") == 1


def test_post_returns_addressed_operation_beyond_recent_history(pilot):
    from datetime import timedelta

    from app.services.haproxy_pilot import PilotOperation

    svc, req, _, calls, _, _, sessions = pilot
    svc.apply(req, "operator")
    with sessions.begin() as db:
        original = db.get(PilotOperation, str(req.operation_id))
        template = {col.key: getattr(original, col.key) for col in PilotOperation.__table__.columns}
        for pos in range(101):
            db.add(
                PilotOperation(
                    **{
                        **template,
                        "operation_id": str(uuid4()),
                        "outcome": "rejected",
                        "created_at": original.created_at + timedelta(seconds=pos + 1),
                    }
                )
            )
    assert len(svc.status().history) == 100
    assert req.operation_id not in {item.operation_id for item in svc.status().history}
    history = svc.apply(req, "operator").history
    assert len(history) == 101 and history[-1].operation_id == req.operation_id
    assert history[-1].outcome == "applied"
    assert calls.count("/haproxy-pilot/apply") == 1


def test_deleted_highest_node_id_can_be_reused_without_inheriting_its_pilot(pilot):
    from app.db import crud
    from app.services import haproxy_pilot as service

    svc, req, state, calls, failures, results, sessions = pilot
    with sessions.begin() as db:
        node = db.get(service.Node, 1)
        node.id = 3
    svc.node_id = 3
    service.xray.nodes[3] = service.xray.nodes.pop(1)
    assert svc.apply(req, "operator").history[0].outcome == "applied"
    failures["/haproxy-pilot/apply"] = 0
    pending = req.model_copy(update={"operation_id": uuid4(), "expected_revision": 1})
    assert svc.apply(pending, "operator").history[0].outcome == "pending"
    with sessions() as db:
        crud.remove_node(db, db.get(service.Node, 3))
        replacement = service.Node(
            name="replacement", address="node1", port=1234, api_port=1235, status="connected", control_session_id="new"
        )
        db.add(replacement)
        db.commit()
        assert replacement.id == 3
        archived = db.get(service.PilotOperation, str(pending.operation_id))
        assert archived.archived_at is not None and archived.outcome == "pending" and archived.pending_node_id is None
    state.update(target=None, enabled=False, revision=0)
    service.xray.nodes[3]._session_id = "new"
    failures.clear()
    assert svc.status().history == []
    with pytest.raises(HTTPException) as conflict:
        svc.apply(pending, "operator")
    assert conflict.value.status_code == 409
    assert svc.apply(req.model_copy(update={"operation_id": uuid4()}), "operator").history[0].outcome == "applied"
