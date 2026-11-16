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
                    result = CollectionResult(data=future.result())
                except Exception as exc:
                    result = CollectionResult(error=exc)
                yield node_id, result
            done.clear()
    finally:
        for future in pending:
            future.cancel()


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
