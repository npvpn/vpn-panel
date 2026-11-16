"""Bounded completion-order сбор и локальный eligibility без REST."""

from __future__ import annotations

import importlib
import importlib.util
import threading
from concurrent.futures import ThreadPoolExecutor


def runtime():
    assert importlib.util.find_spec("app.utils.usage_runtime"), "Нужен независимый bounded usage runtime"
    return importlib.import_module("app.utils.usage_runtime")


def test_ready_result_is_yielded_without_waiting_for_first_node():
    module = runtime()
    release = threading.Event()
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:

            def slow():
                assert release.wait(2)
                return "slow"

            results = module.completed_results(executor, [(1, slow), (2, lambda: "ready")], limit=2)
            node_id, outcome = next(results)
            assert node_id == 2 and outcome.data == "ready" and outcome.error is None
            release.set()
            assert next(results)[0] == 1
    finally:
        release.set()


def test_window_is_bounded_and_api_error_is_not_successful_empty():
    module = runtime()
    submitted = []

    class InlineExecutor:
        def submit(self, func):
            from concurrent.futures import Future

            future = Future()
            submitted.append(future)
            try:
                future.set_result(func())
            except Exception as exc:
                future.set_exception(exc)
            return future

    def broken():
        raise ConnectionError("offline")

    results = module.completed_results(
        InlineExecutor(), [(1, lambda: []), (2, broken)] + [(node, lambda: []) for node in range(3, 165)], limit=4
    )
    first = next(results)
    assert len(submitted) == 4
    all_results = [first] + list(results)
    outcomes = dict(all_results)
    assert outcomes[1].data == [] and outcomes[1].error is None
    assert isinstance(outcomes[2].error, ConnectionError)


def test_snapshot_uses_only_ready_cached_transports():
    module = runtime()

    class Node:
        def __init__(self, ready=True):
            self._started = ready
            self._session_id = "session"
            self._api = object()
            self.usage_coefficient = 1.5

        @property
        def connected(self):
            raise AssertionError

        @property
        def started(self):
            raise AssertionError

        @property
        def api(self):
            raise AssertionError

    active, inactive = Node(), Node(False)
    snapshot = module.ready_apis({1: active, 2: inactive})
    assert snapshot == {1: (active._api, 1.5)}


def test_accounting_leases_exclude_mutation_until_both_kinds_finish():
    """Два вида статистики независимо удерживают lifecycle до SQL."""
    import pytest

    module = runtime()
    state = module.UsageState()
    epoch = state.observe_nodes({1: "one"})[1]
    user = state.acquire_collection(1, epoch)
    node = state.acquire_collection(1, epoch)
    user()
    user()  # cleanup may be called defensively more than once
    with pytest.raises(module.UsageBusyError), state.mutation(1):
        raise AssertionError("mutation started before outbound write")
    node()
    with state.mutation(1):
        assert 1 not in state.observe_nodes({1: "one"})
        with pytest.raises(module.StaleObservationError):
            state.acquire_collection(1, epoch)
    fresh = state.observe_nodes({1: "one"})[1]
    assert fresh != epoch


def test_collection_failure_releases_lease_and_old_epoch_never_resets():
    """Ошибки RPC освобождают guard, старый transport не сбрасывается."""
    import pytest

    module = runtime()
    state = module.UsageState()
    epoch = state.observe_nodes({1: "one"})[1]

    def broken():
        raise ConnectionError("offline")

    with pytest.raises(ConnectionError):
        state.collect(1, epoch, broken)
    with state.mutation(1):
        state.retire_node(1)
    with pytest.raises(module.StaleObservationError):
        state.collect(1, epoch, lambda: (_ for _ in ()).throw(AssertionError("stale reset")))
    with pytest.raises(module.StaleObservationError):
        state.acquire_collection(1, None)


def test_abandoned_results_release_current_and_running_collection_leases():
    """Закрытие consumer освобождает текущий и поздний готовый результаты."""
    import pytest

    module = runtime()
    state = module.UsageState()
    epochs = state.observe_nodes({1: "one", 2: "two"})
    started, release = threading.Event(), threading.Event()

    def slow():
        started.set()
        assert release.wait(3)
        return []

    with ThreadPoolExecutor(max_workers=2) as executor:
        tasks = [
            (1, lambda: state.collect(1, epochs[1], lambda: [])),
            (2, lambda: state.collect(2, epochs[2], slow)),
        ]
        results = module.completed_results(executor, tasks, limit=2)
        try:
            assert next(results)[0] == 1
            assert started.wait(2)
            results.close()
            with state.mutation(1):
                pass
            with pytest.raises(module.UsageBusyError), state.mutation(2):
                raise AssertionError("RPC still running")
        finally:
            release.set()
    with state.mutation(2):
        pass
