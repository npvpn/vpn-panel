"""Admission до executor и тяжёлого конфига; управляемые часы и исполнение."""

from __future__ import annotations

import importlib
import importlib.util
import weakref
from concurrent.futures import Future

import pytest


class Executor:
    def __init__(self):
        self.jobs = []
        self.closed = False

    def submit(self, func, *args):
        future = Future()
        self.jobs.append((future, func, args))
        return future

    def run(self):
        future, func, args = self.jobs.pop(0)
        if future.set_running_or_notify_cancel():
            try:
                future.set_result(func(*args))
            except BaseException as exc:
                future.set_exception(exc)

    def shutdown(self, **_kwargs):
        self.closed = True


def runtime(execute=None, *, concurrency=4, factory=lambda: {}):
    assert importlib.util.find_spec("app.xray.node_operations"), "Нужен bounded admission нод"
    module = importlib.import_module("app.xray.node_operations")
    executor = Executor()
    scheduler = module.NodeOperationScheduler(
        executor,
        execute or (lambda *_args: None),
        factory,
        concurrency=concurrency,
        clock=lambda: 500,
    )
    return module, executor, scheduler


def test_repeated_165_nodes_do_not_queue_wave_per_tick():
    calls = []
    module, executor, scheduler = runtime(factory=lambda: calls.append("build") or {})
    first = {}
    for _tick in range(100):
        for node in range(165):
            future = scheduler.request(node, module.OperationKind.SOFT)
            first.setdefault(node, future)
            assert future is first[node]
    snapshot = scheduler.snapshot()
    assert snapshot["active"] == 4 and snapshot["pending"] == 161
    assert len(executor.jobs) == 4
    assert calls == []
    scheduler.shutdown()
    assert not scheduler.snapshot()["pending"]
    assert all(future.cancelled() for future in first.values())


def test_manual_hard_is_one_next_intent_after_active_soft():
    seen = []
    next_futures = []
    module, executor, scheduler = runtime(concurrency=1)

    def execute(node, kind, config_factory):
        seen.append(kind)
        if kind == module.OperationKind.SOFT:
            next_futures.extend(scheduler.request(node, module.OperationKind.HARD, manual=True) for _ in range(30))
        return config_factory()

    scheduler.execute = execute
    soft = scheduler.request(7, module.OperationKind.SOFT)
    executor.run()
    assert soft.done()
    assert len({id(future) for future in next_futures}) == 1
    assert seen == [module.OperationKind.SOFT]
    executor.run()
    assert seen == [module.OperationKind.SOFT, module.OperationKind.HARD]
    assert next_futures[0].done()
    assert scheduler.snapshot()["active"] == 0


def test_running_admin_mutation_rejected_and_queued_mutation_cancels():
    module, executor, scheduler = runtime(concurrency=1)
    queued = scheduler.request(1, module.OperationKind.SOFT)
    with scheduler.mutation(1):
        assert queued.cancelled()
    assert not scheduler.pending(1)
    executor.run()  # cancelled lease never reaches operation
    calls = []

    def execute(node, *_args):
        with pytest.raises(module.NodeBusyError), scheduler.mutation(node):
            calls.append("invalid mutation")

    scheduler.execute = execute
    scheduler.request(2, module.OperationKind.SOFT)
    executor.run()
    assert calls == []


def test_future_cancel_and_submit_failure_do_not_leave_pending():
    module, executor, scheduler = runtime(concurrency=1)
    first = scheduler.request(1, module.OperationKind.SOFT)
    cancelled = scheduler.request(2, module.OperationKind.SOFT)
    assert cancelled.cancel()
    executor.run()
    assert first.done() and not scheduler.pending(2)

    error = RuntimeError("submit failed")

    def fail(*_args):
        raise error

    executor.submit = fail
    failure = scheduler.request(3, module.OperationKind.SOFT)
    with pytest.raises(RuntimeError, match="submit failed"):
        failure.result()
    assert not scheduler.pending(3)
    assert scheduler.snapshot()["active"] == 0


def test_wave_is_shared_only_within_dispatch_cohort_and_freed():
    refs = []

    class Config(dict):
        pass

    def factory():
        config = Config()
        refs.append(weakref.ref(config))
        return config

    module, executor, scheduler = runtime(concurrency=2, factory=factory)
    seen = []
    scheduler.execute = lambda _node, _kind, get_config: seen.append(id(get_config()))
    scheduler.request_many([(node, module.OperationKind.SOFT) for node in range(4)])
    for _ in range(4):
        executor.run()
    assert seen[0] == seen[1]
    assert len(refs) == 3  # first cohort of two, then fresh snapshots on each free slot
    assert all(ref() is None for ref in refs)


def test_shutdown_keeps_running_owner_and_rejects_new_work():
    module, executor, scheduler = runtime(concurrency=1)

    def execute(node, *_args):
        scheduler.shutdown(wait=False)
        assert scheduler.pending(node)

    scheduler.execute = execute
    running = scheduler.request(1, module.OperationKind.SOFT)
    pending = scheduler.request(2, module.OperationKind.SOFT)
    executor.run()
    assert running.done() and pending.cancelled()
    assert not scheduler.pending(1)
    with pytest.raises(RuntimeError, match="shutdown"):
        scheduler.request(3, module.OperationKind.SOFT).result()


def test_repeated_cancelled_admission_does_not_grow_executor_backlog():
    module, executor, scheduler = runtime(concurrency=1)
    for _ in range(100):
        future = scheduler.request(1, module.OperationKind.SOFT)
        future.cancel()
        with scheduler.mutation(1):
            pass
    assert len(executor.jobs) == 1
    executor.run()
    assert scheduler.snapshot()["active"] == 0


def test_mutation_marks_lease_cancelled_before_future_callbacks():
    module, executor, scheduler = runtime(concurrency=1)
    called = []
    scheduler.execute = lambda *_args: called.append("REST must not start")
    future = scheduler.request(1, module.OperationKind.SOFT)
    original_cancel = future.cancel
    ran = []

    def interleaved_cancel():
        if not ran:
            ran.append(True)
            executor.run()  # exact handoff after scheduler unlock, before Future.cancel
        return original_cancel()

    future.cancel = interleaved_cancel
    with scheduler.mutation(1):
        called.append("DB mutation")
    assert called == ["DB mutation"]


def test_new_manual_restart_uses_next_snapshot_after_running_hard():
    module, executor, scheduler = runtime(concurrency=1)
    version = [1]
    snapshots = []
    scheduler.config_factory = lambda: version[0]
    next_future = []

    def execute(node, kind, factory):
        snapshots.append(factory())
        if kind == module.OperationKind.HARD:
            version[0] = 2
            next_future.append(scheduler.request(node, module.OperationKind.RESTART, manual=True))

    scheduler.execute = execute
    first = scheduler.request(1, module.OperationKind.HARD, manual=True)
    executor.run()
    assert next_future[0] is not first and not next_future[0].done()
    executor.run()
    assert snapshots == [1, 2]


def test_cancelled_waiting_future_does_not_swallow_new_manual_request():
    module, executor, scheduler = runtime(concurrency=1)
    calls = []
    scheduler.execute = lambda node, kind, _factory: calls.append((node, kind))
    scheduler.request(1, module.OperationKind.SOFT)
    cancelled = scheduler.request(2, module.OperationKind.SOFT)
    assert cancelled.cancel()
    fresh = scheduler.request(2, module.OperationKind.HARD, manual=True)
    assert fresh is not cancelled and not fresh.cancelled()
    executor.run()
    executor.run()
    assert calls[-1] == (2, module.OperationKind.HARD)


def test_manual_request_does_not_inherit_already_built_cohort_config():
    module, executor, scheduler = runtime(concurrency=2)
    version = [1]
    calls = []
    scheduler.config_factory = lambda: version[0]
    scheduler.execute = lambda node, _kind, factory: calls.append((node, factory()))
    old = scheduler.request_many([(1, module.OperationKind.HARD), (2, module.OperationKind.HARD)])
    executor.run()  # node1 built shared version1; node2 has not entered worker
    version[0] = 2
    fresh = scheduler.request(2, module.OperationKind.RESTART, manual=True)
    assert fresh is not old[1]
    executor.run()
    executor.run()
    assert calls == [(1, 1), (2, 1), (2, 2)]
