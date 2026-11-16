"""Реальный вход connect/restart не держит конфиги в общей очереди."""

from __future__ import annotations

import importlib
import sys
import types
import weakref
from unittest.mock import Mock

from app.xray.node_operations import NodeOperationScheduler, OperationKind
from tests.test_node_operations import Executor


def load_operations(monkeypatch):
    share = types.ModuleType("app.subscription.share")
    share.generate_v2ray_links = lambda *_args, **_kwargs: []
    with monkeypatch.context() as patch:
        patch.setitem(sys.modules, "app.subscription.share", share)
        return importlib.import_module("app.xray.operations")


def test_entrypoint_admits_before_config_and_does_not_keep_caller_wave(monkeypatch):
    operations = load_operations(monkeypatch)
    assert hasattr(operations, "get_node_scheduler"), "Нужен admission до threaded_function"
    executor = Executor()
    execute = Mock()
    factory = Mock(return_value={})
    scheduler = NodeOperationScheduler(executor, execute, factory, concurrency=1)
    monkeypatch.setattr(operations, "get_node_scheduler", lambda: scheduler)

    class Config(dict):
        pass

    for _ in range(100):
        config = Config()
        reference = weakref.ref(config)
        operations.connect_node(7, config)
        del config
        assert reference() is None
    assert len(executor.jobs) == 1 and factory.call_count == 0
    executor.run()
    assert execute.call_args.args[:2] == (7, OperationKind.SOFT)


def test_stale_execution_guard_is_never_reclaimed(monkeypatch):
    operations = load_operations(monkeypatch)
    monkeypatch.setattr(operations, "_connecting_nodes", set())
    monkeypatch.setattr(operations, "_connecting_started_at", {})
    monkeypatch.setattr(operations, "_connecting_generation", {})
    first = operations._acquire_connect_slot(42)
    operations._connecting_started_at[42] = 0
    assert operations._acquire_connect_slot(42, force=True) is None
    operations._release_connect_slot(42, first)
