"""Локальная готовность transport и ограниченный сбор по мере завершения."""

from __future__ import annotations

import threading
import time
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import FIRST_COMPLETED, Executor, Future, wait
from contextlib import contextmanager
from dataclasses import dataclass
from math import ceil
from typing import Any


@dataclass
class CollectionResult:
    data: Any = None
    error: Exception | None = None
    release: Callable[[], None] | None = None

    def close(self):
        if self.release is not None:
            self.release()
            self.release = None


def ready_apis(nodes: dict) -> dict:
    ready = {}
    for node_id, node in list(nodes.items()):
        cached = vars(node)
        rest_ready = cached.get("_started") is True and bool(cached.get("_session_id"))
        rpyc_ready = cached.get("started") is True and cached.get("connection") is not None
        api = cached.get("_api")
        if (rest_ready or rpyc_ready) and api is not None:
            ready[node_id] = (api, cached.get("usage_coefficient", 1))
    return ready


def completed_results(
    executor: Executor,
    tasks: Iterable[tuple[int | None, Callable]],
    *,
    limit: int,
) -> Iterator[tuple[int | None, CollectionResult]]:
    source = iter(tasks)
    pending: dict[Future, int | None] = {}
    exhausted = False
    try:
        while pending or not exhausted:
            while not exhausted and len(pending) < max(1, limit):
                try:
                    node_id, collect = next(source)
                except StopIteration:
                    exhausted = True
                    break
                try:
                    future = executor.submit(collect)
                except Exception as exc:
                    future = Future()
                    future.set_exception(exc)
                pending[future] = node_id
            if not pending:
                break
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                node_id = pending.pop(future)
                try:
                    value = future.result()
                    result = value if isinstance(value, CollectionResult) else CollectionResult(data=value)
                except Exception as exc:
                    result = CollectionResult(error=exc)
                try:
                    yield node_id, result
                finally:
                    result.close()
            done.clear()
    finally:

        def release_abandoned(future):
            if not future.cancelled() and future.exception() is None:
                value = future.result()
                if isinstance(value, CollectionResult):
                    value.close()

        for future in pending:
            future.cancel()
            future.add_done_callback(release_abandoned)


# Registry owns timestamps and bounded-cardinality counters; no DB/network on scrape.
@dataclass
class UsageStamp:
    since: float
    success: float = 0


@dataclass
class Tick:
    failed: bool = False


class StaleObservationError(RuntimeError):
    """Lifecycle изменился во время чтения metadata; delta ещё не сброшена."""


class UsageBusyError(RuntimeError):
    """Нельзя менять ноду до записи уже сброшенной delta."""


class UsageState:
    def __init__(
        self, *, periods: dict[str, int] | None = None, workers: int = 20, clock: Callable[[], float] = time.time
    ) -> None:
        self.periods = periods or {"user": 10, "node": 30}
        self.workers = max(1, workers)
        self.clock = clock
        self._lock = threading.Lock()
        self._names: dict[int, str] = {}
        self._epochs: dict[int, int] = {}
        self._generation = 0
        self._revision = 0
        self._collecting: Counter = Counter()
        self._mutating: set[int] = set()
        self._paused: set[int] = set()
        self._idle_callbacks: dict[int, Callable[[], None]] = {}
        self._stamps: dict[tuple[int, str], UsageStamp] = {}
        self._errors: Counter = Counter()
        self._ticks: Counter = Counter()
        self._running: Counter = Counter()

    def configure(self, *, periods, workers):
        with self._lock:
            self.periods = periods
            self.workers = max(1, workers)

    def metadata_revision(self) -> int:
        with self._lock:
            return self._revision

    def acquire_collection(self, node_id: int | None, epoch: int | None) -> Callable[[], None]:
        # Core has no editable Node metadata. Remote reset and SQL share a lease;
        # no registry mutex is held across network or database work.
        with self._lock:
            if node_id is not None and (
                epoch is None
                or self._epochs.get(node_id) != epoch
                or node_id in self._mutating
                or node_id in self._paused
            ):
                raise StaleObservationError()
            self._collecting[node_id] += 1
        released = False

        def release():
            nonlocal released
            callback = None
            with self._lock:
                if not released:
                    self._collecting[node_id] -= 1
                    if not self._collecting[node_id]:
                        del self._collecting[node_id]
                        callback = self._idle_callbacks.pop(node_id, None)
                    released = True
            if callback is not None:
                callback()

        return release

    def pause(self, node_id: int) -> None:
        with self._lock:
            if node_id not in self._paused:
                self._paused.add(node_id)
                self._revision += 1

    def resume(self, node_id: int) -> None:
        with self._lock:
            self._paused.discard(node_id)
            self._idle_callbacks.pop(node_id, None)
            self._revision += 1

    def when_idle(self, node_id: int, callback: Callable[[], None]) -> None:
        with self._lock:
            if self._collecting[node_id]:
                self._idle_callbacks[node_id] = callback
                return
        callback()

    @contextmanager
    def edit(self, node_id: int):
        # Caller serializes edits per node. Existing leases retain their delta.
        with self._lock:
            paused = node_id in self._paused
            self._paused.add(node_id)
            self._revision += 1
        try:
            yield
        except BaseException:
            if not paused:
                self.resume(node_id)
            raise
        else:
            self.retire_node(node_id)

    @contextmanager
    def mutation(self, node_id: int):
        with self._lock:
            if self._collecting[node_id] or node_id in self._mutating:
                raise UsageBusyError()
            self._mutating.add(node_id)
            self._revision += 1
        try:
            yield
        finally:
            with self._lock:
                self._mutating.remove(node_id)
                self._revision += 1

    def collect(self, node_id: int | None, epoch: int | None, read: Callable) -> CollectionResult:
        release = self.acquire_collection(node_id, epoch)
        try:
            return CollectionResult(data=read(), release=release)
        except BaseException:
            release()
            raise

    def retire_node(self, node_id: int) -> None:
        with self._lock:
            self._revision += 1
            self._names.pop(node_id, None)
            self._epochs.pop(node_id, None)
            for kind in self.periods:
                self._stamps.pop((node_id, kind), None)

    def observe_nodes(self, enabled: dict[int, str], *, revision: int | None = None) -> dict[int, int]:
        with self._lock:
            if revision is not None and revision != self._revision:
                raise StaleObservationError()
            enabled = {
                node: name for node, name in enabled.items() if node not in self._mutating and node not in self._paused
            }
            if self._names != enabled:
                self._revision += 1
            now = self.clock()
            for node in self._names.keys() - enabled.keys():
                self._epochs.pop(node, None)
                for kind in self.periods:
                    self._stamps.pop((node, kind), None)
            for node in enabled.keys() - self._names.keys():
                self._generation += 1
                self._epochs[node] = self._generation
                for kind in self.periods:
                    self._stamps[(node, kind)] = UsageStamp(now)
            self._names = dict(enabled)
            return dict(self._epochs)

    def mark_success(self, node_id, kind, epoch):
        with self._lock:
            if node_id in self._epochs and self._epochs[node_id] == epoch:
                self._stamps[(node_id, kind)].success = self.clock()

    def mark_failure(self, kind, stage):
        with self._lock:
            self._errors[(kind, stage)] += 1

    @contextmanager
    def track_tick(self, kind):
        tick = Tick()
        with self._lock:
            self._running[kind] += 1
        try:
            yield tick
        except BaseException:
            tick.failed = True
            raise
        finally:
            with self._lock:
                self._running[kind] -= 1
                self._ticks[(kind, "partial_failure" if tick.failed else "success")] += 1

    def snapshot(self):
        with self._lock:
            now = self.clock()
            # Both bounded jobs share usage workers. A user query can occupy a
            # slot for30s and outbound query for10s; include both in queue budget.
            budget = ceil((len(self._names) + 1) / self.workers) * (30 + 10)
            return {
                "nodes": [
                    {
                        "name": self._names[node],
                        "kind": kind,
                        "since": stamp.since,
                        "last_success": stamp.success,
                        "delay": max(0, now - (stamp.success or stamp.since)),
                        "threshold": 2 * self.periods[kind] + budget,
                    }
                    for (node, kind), stamp in self._stamps.items()
                ],
                "errors": dict(self._errors),
                "ticks": dict(self._ticks),
                "running": dict(self._running),
            }


usage_state = UsageState()
