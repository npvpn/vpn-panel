"""Свежесть учитывается по ноде, не маскируется пустым ответом/общим успехом."""

from __future__ import annotations

import importlib

from tests.test_record_usage_pipeline import API, Node, pipeline_fixture  # noqa: F401


def state(clock=lambda: 100):
    module = importlib.import_module("app.utils.usage_runtime")
    assert hasattr(module, "UsageState"), "Нужен per-node successful accounting"
    return module.UsageState(periods={"user": 10, "node": 30}, workers=20, clock=clock)


def test_never_successful_node_has_finite_startup_grace_and_independent_age():
    now = [100]
    runtime = state(lambda: now[0])
    tokens = runtime.observe_nodes({1: "one", 2: "two"})
    now[0] = 110
    runtime.mark_success(1, "user", tokens[1])
    now[0] = 170
    rows = {r["name"]: r for r in runtime.snapshot()["nodes"] if r["kind"] == "user"}
    assert rows["one"]["last_success"] == 110 and rows["one"]["delay"] == 60
    assert rows["two"]["last_success"] == 0 and rows["two"]["delay"] == 70
    assert rows["two"]["threshold"] == 60  # 2*10+ceil(3/20)*(30+10)
    assert rows["two"]["delay"] > rows["two"]["threshold"]


def test_disabled_node_retires_and_old_result_cannot_refresh_new_generation():
    now = [100]
    runtime = state(lambda: now[0])
    first = runtime.observe_nodes({1: "one"})
    runtime.observe_nodes({})
    assert runtime.snapshot()["nodes"] == []
    now[0] = 120
    second = runtime.observe_nodes({1: "renamed"})
    runtime.mark_success(1, "user", first[1])
    row = next(r for r in runtime.snapshot()["nodes"] if r["kind"] == "user")
    assert row["since"] == 120 and row["last_success"] == 0 and second[1] != first[1]


def test_zero_traffic_refreshes_but_write_error_does_not(pipeline, monkeypatch):
    job, _engine = pipeline
    from concurrent.futures import ThreadPoolExecutor
    from types import SimpleNamespace

    runtime = state()
    monkeypatch.setattr(job, "usage_state", runtime, raising=False)
    zero = API(None)
    monkeypatch.setattr(job, "xray", SimpleNamespace(api=API(None), nodes={1: Node(zero)}))
    with ThreadPoolExecutor(max_workers=2) as executor:
        monkeypatch.setattr(job, "get_usage_executor", lambda: executor)
        job.record_user_usages()
        row = next(r for r in runtime.snapshot()["nodes"] if r["kind"] == "user" and r["name"] == "node1")
        assert row["last_success"] == 100
        runtime.observe_nodes({})
        faulty = API(1)
        monkeypatch.setattr(job, "xray", SimpleNamespace(api=API(None), nodes={1: Node(faulty)}))

        def fail(*_args):
            raise RuntimeError("write")

        monkeypatch.setattr(job, "safe_execute", fail)
        job.record_user_usages()
    row = next(r for r in runtime.snapshot()["nodes"] if r["kind"] == "user" and r["name"] == "node1")
    assert row["last_success"] == 0
    assert faulty.calls == 1
    assert runtime.snapshot()["ticks"][("user", "partial_failure")] == 1


def test_retirement_invalidates_pre_mutation_metadata_and_old_success():
    runtime = state()
    old = runtime.observe_nodes({1: "old"})
    assert hasattr(runtime, "metadata_revision"), "Нужен lifecycle revision до DB read"
    revision = runtime.metadata_revision()
    runtime.retire_node(1)
    runtime.observe_nodes({1: "new"}, revision=runtime.metadata_revision())
    import pytest

    from app.utils.usage_runtime import StaleObservationError

    with pytest.raises(StaleObservationError):
        runtime.observe_nodes({1: "old"}, revision=revision)
    runtime.mark_success(1, "user", old[1])
    rows = [r for r in runtime.snapshot()["nodes"] if r["kind"] == "user"]
    assert rows[0]["name"] == "new" and rows[0]["last_success"] == 0


def test_stale_metadata_is_retried_before_any_reset(pipeline, monkeypatch):
    job, _engine = pipeline
    from concurrent.futures import ThreadPoolExecutor
    from types import SimpleNamespace

    from sqlalchemy.orm import Session

    from app.db.models import Node as DBNode

    runtime = state()
    assert hasattr(runtime, "retire_node")
    monkeypatch.setattr(job, "usage_state", runtime)
    api = API(1)
    monkeypatch.setattr(job, "xray", SimpleNamespace(api=API(None), nodes={1: Node(api)}))
    original = Session.query
    retired = []

    def query(db, *entities, **kwargs):
        if entities and entities[0] is DBNode.id and not retired:
            retired.append(True)
            runtime.retire_node(1)
        return original(db, *entities, **kwargs)

    monkeypatch.setattr(Session, "query", query)
    with ThreadPoolExecutor(max_workers=2) as executor:
        monkeypatch.setattr(job, "get_usage_executor", lambda: executor)
        job.record_user_usages()
        assert api.calls == 0
        job.record_user_usages()
        assert api.calls == 1
