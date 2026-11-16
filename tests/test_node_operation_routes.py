"""Edit/Delete отвечают busy409 до изменений, queued lease отменяется."""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import BackgroundTasks, HTTPException

from app.xray.node_operations import NodeOperationScheduler, OperationKind
from tests.test_node_operations import Executor


def load_route(monkeypatch):
    share = types.ModuleType("app.subscription.share")
    share.generate_v2ray_links = lambda *_args, **_kwargs: []
    with monkeypatch.context() as patch:
        patch.setitem(sys.modules, "app.subscription.share", share)
        spec = importlib.util.spec_from_file_location(
            "node_routes_test", Path(__file__).parents[1] / "app/routers/node.py"
        )
        route = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(route)
    operations = importlib.import_module("app.xray.operations")
    monkeypatch.setattr(route.xray, "operations", operations, raising=False)
    monkeypatch.setattr(route.xray, "hosts", SimpleNamespace(update=Mock()), raising=False)
    monkeypatch.setattr(route, "crud", Mock())
    return route, operations


@pytest.mark.parametrize("action", ["edit", "delete"])
def test_busy_operation_blocks_admin_before_database_change(monkeypatch, action):
    route, operations = load_route(monkeypatch)
    assert hasattr(operations, "node_mutation")
    executor = Executor()
    scheduler = NodeOperationScheduler(executor, lambda *_: None, lambda: {}, concurrency=1)
    monkeypatch.setattr(operations, "get_node_scheduler", lambda: scheduler)

    def execute(*_args):
        node = SimpleNamespace(id=7, name="test")
        with pytest.raises(HTTPException) as exc:
            if action == "edit":
                route.modify_node(SimpleNamespace(), BackgroundTasks(), node, Mock(), Mock())
            else:
                route.remove_node(node, Mock(), Mock())
        assert exc.value.status_code == 409

    scheduler.execute = execute
    future = scheduler.request(7, OperationKind.SOFT)
    executor.run()
    future.result()
    route.crud.update_node.assert_not_called()
    route.crud.remove_node.assert_not_called()


def test_queued_edit_cancels_old_intent_and_does_not_execute_it(monkeypatch):
    route, operations = load_route(monkeypatch)
    executor = Executor()
    execute = Mock()
    scheduler = NodeOperationScheduler(executor, execute, lambda: {}, concurrency=1)
    monkeypatch.setattr(operations, "get_node_scheduler", lambda: scheduler)
    monkeypatch.setattr(operations, "remove_node", Mock())
    old = scheduler.request(7, OperationKind.SOFT)
    node = SimpleNamespace(id=7, name="test", status=route.NodeStatus.disabled)
    route.crud.update_node.return_value = node
    route.modify_node(SimpleNamespace(), BackgroundTasks(), node, Mock(), Mock())
    assert old.cancelled()
    executor.run()
    execute.assert_not_called()
    route.crud.update_node.assert_called_once()


def test_successful_edit_retires_prior_usage_generation(monkeypatch):
    route, operations = load_route(monkeypatch)
    from app.utils.usage_runtime import UsageState

    state = UsageState(clock=lambda: 100)
    assert hasattr(route, "usage_state"), "Mutation должна инвалидировать freshness"
    monkeypatch.setattr(route, "usage_state", state)
    old = state.observe_nodes({7: "test"})
    scheduler = NodeOperationScheduler(Executor(), lambda *_: None, lambda: {}, concurrency=1)
    monkeypatch.setattr(operations, "get_node_scheduler", lambda: scheduler)
    monkeypatch.setattr(operations, "remove_node", Mock())
    node = SimpleNamespace(id=7, name="test", status=route.NodeStatus.disabled)
    route.crud.update_node.return_value = node
    route.modify_node(SimpleNamespace(), BackgroundTasks(), node, Mock(), Mock())
    assert state.snapshot()["nodes"] == []
    state.observe_nodes({7: "test"})
    state.mark_success(7, "user", old[7])
    assert all(row["last_success"] == 0 for row in state.snapshot()["nodes"])


def test_collection_during_transport_removal_cannot_refresh_after_edit(monkeypatch):
    route, operations = load_route(monkeypatch)
    from app.utils.usage_runtime import UsageState

    state = UsageState(clock=lambda: 100)
    state.observe_nodes({7: "test"})
    monkeypatch.setattr(route, "usage_state", state)
    scheduler = NodeOperationScheduler(Executor(), lambda *_: None, lambda: {}, concurrency=1)
    monkeypatch.setattr(operations, "get_node_scheduler", lambda: scheduler)
    old_results = []

    def remove(_node):
        # DB metadata already committed, old transport can still return stats
        # while a synchronous disconnect is in progress.
        old_results.append(state.observe_nodes({7: "test"}, revision=state.metadata_revision())[7])

    monkeypatch.setattr(operations, "remove_node", remove)
    node = SimpleNamespace(id=7, name="test", status=route.NodeStatus.disabled)
    route.crud.update_node.return_value = node
    route.modify_node(SimpleNamespace(), BackgroundTasks(), node, Mock(), Mock())
    state.observe_nodes({7: "test"})
    state.mark_success(7, "user", old_results[0])
    assert all(row["last_success"] == 0 for row in state.snapshot()["nodes"])


def test_cancelled_reconnect_future_returns_busy_instead_of_server_error(monkeypatch):
    route, operations = load_route(monkeypatch)
    from concurrent.futures import Future

    future = Future()
    future.cancel()
    monkeypatch.setattr(operations, "connect_node", Mock(return_value=future))
    with pytest.raises(HTTPException) as exc:
        route.reconnect_node(dbnode=SimpleNamespace(id=7), _=Mock())
    assert exc.value.status_code == 409 and "повторите" in exc.value.detail
