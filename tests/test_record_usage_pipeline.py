"""Настоящие SQL-записи готовы раньше медленной ноды; reset не повторяется."""

from __future__ import annotations

import importlib
import sys
import threading
import types
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.node import NodeStatus


@pytest.fixture(name="pipeline")
def pipeline_fixture(monkeypatch):
    share = types.ModuleType("app.subscription.share")
    share.generate_v2ray_links = lambda *_args, **_kwargs: []
    with monkeypatch.context() as patch:
        patch.setitem(sys.modules, "app.subscription.share", share)
        job = importlib.import_module("app.jobs.record_usages")
    from app.db.base import Base
    from app.db.models import Admin, Node, User

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        admin = Admin(username="owner")
        db.add(admin)
        db.flush()
        db.add_all([User(id=1, username="first", admin_id=admin.id), User(id=2, username="second", admin_id=admin.id)])
        db.add_all(
            [Node(id=node, name=f"node{node}", address="127.0.0.1", port=62050, api_port=62051) for node in (1, 2)]
        )
        db.commit()

    @contextmanager
    def get_db():
        with Session(engine) as db:
            yield db

    monkeypatch.setattr(job, "GetDB", get_db)
    monkeypatch.setattr(job, "DISABLE_RECORDING_NODE_USER_USAGE", False)
    yield job, engine
    engine.dispose()


class API:
    def __init__(self, uid, release=None):
        self.uid = uid
        self.release = release
        self.calls = 0

    def get_users_stats(self, **_kwargs):
        self.calls += 1
        if self.release is not None:
            assert self.release.wait(3), "slow API was not released"
        if self.uid is None:
            return []
        return [SimpleNamespace(value=100, name=f"{self.uid}.user")]


class Node:
    def __init__(self, api, coefficient=1):
        self._started = True
        self._session_id = "session"
        self._api = api
        self.usage_coefficient = coefficient

    @property
    def connected(self):
        raise AssertionError

    @property
    def started(self):
        raise AssertionError


def test_fast_node_is_recorded_while_slow_node_is_still_collecting(pipeline, monkeypatch):
    job, engine = pipeline
    from app.db.models import Admin, NodeUserUsage, User

    release = threading.Event()
    written = threading.Event()
    slow, fast = API(1, release), API(2)
    monkeypatch.setattr(job, "xray", SimpleNamespace(api=API(None), nodes={1: Node(slow), 2: Node(fast, 1.5)}))
    original = job.record_user_stats

    def record(params, node_id, coefficient):
        original(params, node_id, coefficient)
        if node_id == 2:
            written.set()

    monkeypatch.setattr(job, "record_user_stats", record)
    errors = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        monkeypatch.setattr(job, "get_usage_executor", lambda: executor, raising=False)

        def run():
            try:
                job.record_user_usages()
            except Exception as exc:
                errors.append(exc)

        thread = threading.Thread(target=run)
        thread.start()
        try:
            assert written.wait(2), f"ready node was blocked: {errors}"
            with Session(engine) as db:
                assert db.get(User, 2).used_traffic == 150
                assert db.query(NodeUserUsage).filter_by(node_id=2).one().used_traffic == 150
            assert thread.is_alive()
        finally:
            release.set()
            thread.join(4)
    assert not errors and not thread.is_alive()
    assert slow.calls == fast.calls == 1
    with Session(engine) as db:
        assert db.get(User, 1).used_traffic == 100
        assert db.query(Admin).one().users_usage == 250


def test_collect_error_is_not_successful_empty(pipeline):
    job, _engine = pipeline

    class Broken:
        def get_users_stats(self, **_kwargs):
            from xray_api import exc as api_exc

            raise api_exc.XrayError("offline")

    from xray_api import exc as api_exc

    with pytest.raises(api_exc.XrayError):
        job.get_users_stats(Broken())


def test_admin_mapping_failure_does_not_discard_primary_user_usage(pipeline, monkeypatch):
    job, engine = pipeline
    from app.db.models import User
    from app.utils.usage_runtime import UsageState

    state = UsageState(clock=lambda: 100)
    monkeypatch.setattr(job, "usage_state", state)
    api = API(1)
    monkeypatch.setattr(job, "xray", SimpleNamespace(api=API(None), nodes={1: Node(api)}))
    original = Session.query

    def query(db, *entities, **kwargs):
        if len(entities) == 2 and entities[0] is User.id and entities[1] is User.admin_id:
            raise RuntimeError("admin-map")
        return original(db, *entities, **kwargs)

    monkeypatch.setattr(Session, "query", query)
    with ThreadPoolExecutor(max_workers=2) as executor:
        monkeypatch.setattr(job, "get_usage_executor", lambda: executor)
        job.record_user_usages()
    with Session(engine) as db:
        assert db.get(User, 1).used_traffic == 100
    row = next(r for r in state.snapshot()["nodes"] if r["kind"] == "user" and r["name"] == "node1")
    assert row["last_success"] == 0
    assert api.calls == 1


@pytest.mark.parametrize("disable_history", [False, True])
def test_outbound_pipeline_writes_ready_node_and_preserves_error_freshness(pipeline, monkeypatch, disable_history):
    job, engine = pipeline
    from app.db.models import NodeUsage, System
    from app.utils.usage_runtime import UsageState

    with Session(engine) as db:
        db.add(System(id=1))
        db.commit()
    state = UsageState(clock=lambda: 100)
    monkeypatch.setattr(job, "usage_state", state)
    monkeypatch.setattr(job, "DISABLE_RECORDING_NODE_USAGE", disable_history)
    release = threading.Event()
    written = threading.Event()

    class Outbound:
        def __init__(self, *, empty=False, slow=False):
            self.empty, self.slow, self.calls = empty, slow, 0

        def get_outbounds_stats(self, **_kwargs):
            self.calls += 1
            if self.slow:
                assert release.wait(3)
                raise ConnectionError("offline")
            return (
                []
                if self.empty
                else [
                    SimpleNamespace(value=80, link="uplink"),
                    SimpleNamespace(value=20, link="downlink"),
                ]
            )

    fast, slow = Outbound(), Outbound(slow=True)
    monkeypatch.setattr(job, "xray", SimpleNamespace(api=Outbound(empty=True), nodes={1: Node(fast), 2: Node(slow)}))
    original = job._write_usage

    def write(kind, node, stage, action):
        result = original(kind, node, stage, action)
        if kind == "node" and node == 1 and stage == ("totals" if disable_history else "history"):
            written.set()
        return result

    monkeypatch.setattr(job, "_write_usage", write)
    errors = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        monkeypatch.setattr(job, "get_usage_executor", lambda: executor)

        def run():
            try:
                job.record_node_usages()
            except Exception as exc:
                errors.append(exc)

        thread = threading.Thread(target=run)
        thread.start()
        try:
            assert written.wait(2), errors
            with Session(engine) as db:
                total = db.get(System, 1)
                assert (total.uplink, total.downlink) == (80, 20)
                assert db.query(NodeUsage).count() == (0 if disable_history else 1)
            assert thread.is_alive()
        finally:
            release.set()
            thread.join(4)
    assert not errors
    rows = {r["name"]: r for r in state.snapshot()["nodes"] if r["kind"] == "node"}
    assert rows["node1"]["last_success"] == 100 and rows["node2"]["last_success"] == 0
    assert fast.calls == slow.calls == 1


def test_job_keeps_bs_owner_billable_wiring(pipeline, monkeypatch):
    job, engine = pipeline
    from unittest.mock import Mock

    from app.db.models import Node as DBNode

    with Session(engine) as db:
        db.get(DBNode, 1).is_bs = True
        db.get(DBNode, 2).is_bs = True
        db.get(DBNode, 2).owner_bot_id = 777
        db.commit()
    monkeypatch.setattr(job, "xray", SimpleNamespace(api=API(None), nodes={1: Node(API(1)), 2: Node(API(2), 1.5)}))
    record_bs = Mock()
    monkeypatch.setattr(job, "record_bs_user_stats", record_bs)
    with ThreadPoolExecutor(max_workers=3) as executor:
        monkeypatch.setattr(job, "get_usage_executor", lambda: executor)
        job.record_user_usages()
    actual = {call.args[1]: call.args[2:] for call in record_bs.call_args_list}
    assert actual == {1: (1, True), 2: (1.5, False)}


@pytest.mark.parametrize("kind", ["user", "node"])
def test_queued_retired_collection_does_not_reset_or_write(pipeline, monkeypatch, kind):
    """Изменение ноды после snapshot отменяет ещё не начавшийся reset."""
    from concurrent.futures import Future

    from app.utils.usage_runtime import UsageState

    job, _engine = pipeline
    state = UsageState()
    monkeypatch.setattr(job, "usage_state", state)

    class Stats(API):
        def get_outbounds_stats(self, **kwargs):
            self.calls += 1
            return []

    remote = Stats(1)
    monkeypatch.setattr(job, "xray", SimpleNamespace(api=Stats(None), nodes={1: Node(remote)}))

    class RetiringExecutor:
        def __init__(self):
            self.count = 0

        def submit(self, collect):
            self.count += 1
            if self.count == 2:
                state.retire_node(1)
            result = Future()
            try:
                result.set_result(collect())
            except Exception as exc:
                result.set_exception(exc)
            return result

    monkeypatch.setattr(job, "get_usage_executor", RetiringExecutor)
    getattr(job, f"record_{kind}_usages")()
    assert remote.calls == 0


@pytest.mark.parametrize("action", ["edit", "delete"])
def test_node_mutation_is_busy_until_collected_delta_is_written(pipeline, monkeypatch, action):
    """Изменять владельца/коэффициент между reset и SQL нельзя."""
    from unittest.mock import Mock

    from fastapi import BackgroundTasks, HTTPException

    from app.utils.usage_runtime import UsageState
    from tests.test_node_operation_routes import load_route

    job, _engine = pipeline
    route, operations = load_route(monkeypatch)
    state = UsageState()
    monkeypatch.setattr(job, "usage_state", state)
    # Keep the read model and lifecycle service on the same process registry.
    monkeypatch.setattr(route.node_lifecycle, "usage_state", state)
    from app.xray.node_operations import NodeOperationScheduler
    from tests.test_node_operations import Executor

    monkeypatch.setattr(operations, "get_node_scheduler", lambda: NodeOperationScheduler(Executor(), Mock(), Mock()))
    monkeypatch.setattr(operations, "remove_node", Mock())
    reset_finished, release_write = threading.Event(), threading.Event()
    monkeypatch.setattr(job, "xray", SimpleNamespace(api=API(None), nodes={1: Node(API(1))}))
    original = job._record_user_node

    def write(params, node_id, *args):
        if node_id == 1:
            reset_finished.set()
            assert release_write.wait(3)
        return original(params, node_id, *args)

    monkeypatch.setattr(job, "_record_user_node", write)
    errors = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        monkeypatch.setattr(job, "get_usage_executor", lambda: executor)

        def run():
            try:
                job.record_user_usages()
            except Exception as exc:
                errors.append(exc)

        thread = threading.Thread(target=run)
        thread.start()
        try:
            assert reset_finished.wait(2), errors
            node = SimpleNamespace(id=1, name="node1", status=NodeStatus.disabled)
            route.crud.update_node.return_value = node
            with pytest.raises(HTTPException) as exc:
                if action == "edit":
                    route.modify_node(SimpleNamespace(), BackgroundTasks(), node, Mock(), Mock())
                else:
                    route.remove_node(node, Mock(), Mock())
            assert exc.value.status_code == 409
            route.crud.update_node.assert_not_called()
            route.crud.remove_node.assert_not_called()
        finally:
            release_write.set()
            thread.join(4)
    assert not errors and not thread.is_alive()
