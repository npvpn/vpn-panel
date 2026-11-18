"""Ограниченный admission команд нод; ожидание хранит только лёгкие намерения."""

from __future__ import annotations

import logging
import threading
import time
from collections import Counter, OrderedDict
from collections.abc import Callable
from concurrent.futures import Executor, Future
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

logger = logging.getLogger(__name__)


class OperationKind(IntEnum):
    SOFT = 0
    RESTART = 1
    HARD = 2


class NodeBusyError(RuntimeError):
    def __init__(self):
        super().__init__("Нода занята текущей операцией; повторите после её завершения")


class ConfigWave:
    """Снимок живёт только в cohort исполняемых работ, никогда в pending."""

    def __init__(self, factory: Callable[[], Any]):
        self.factory = factory
        self.lock = threading.Lock()
        self.ready = False
        self.value: Any = None
        self.error: BaseException | None = None

    def get(self):
        with self.lock:
            if not self.ready:
                try:
                    self.value = self.factory()
                except BaseException as exc:
                    self.error = exc
                self.ready = True
            if self.error is not None:
                raise self.error
            return self.value


@dataclass
class Intent:
    node_id: int
    kind: OperationKind
    queued_at: float
    future: Future = field(default_factory=Future)
    running: bool = False
    cancel_requested: bool = False


class NodeOperationScheduler:
    def __init__(
        self,
        executor: Executor,
        execute: Callable,
        config_factory: Callable,
        *,
        concurrency: int,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.executor = executor
        self.execute = execute
        self.config_factory = config_factory
        self.concurrency = max(1, concurrency)
        self.clock = clock
        self._lock = threading.RLock()
        self._waiting: OrderedDict[int, Intent] = OrderedDict()
        self._active: dict[int, Intent] = {}
        self._mutating: set[int] = set()
        self._closed = False
        self._outcomes: Counter = Counter()

    def request(self, node_id: int, kind: OperationKind, *, manual: bool = False) -> Future:
        return self.request_many([(node_id, kind)], manual=manual)[0]

    def request_many(self, requests, *, manual: bool = False) -> list[Future]:
        futures = []
        failures: list[tuple[Future, BaseException]] = []
        with self._lock:
            for node_id, kind in requests:
                if self._closed or node_id in self._mutating:
                    error = RuntimeError("node scheduler shutdown") if self._closed else NodeBusyError()
                    self._outcomes[(kind.name.lower(), "rejected")] += 1
                    rejected: Future = Future()
                    failures.append((rejected, error))
                    futures.append(rejected)
                else:
                    futures.append(self._admit(node_id, kind, manual))
            failures.extend(self._dispatch())
        self._fail(failures)
        return futures

    def _admit(self, node_id: int, kind: OperationKind, manual: bool) -> Future:
        active = self._active.get(node_id)
        if active is not None and not active.cancel_requested and not active.future.cancelled() and not manual:
            self._outcomes[(kind.name.lower(), "coalesced")] += 1
            return active.future
        pending = self._waiting.get(node_id)
        if pending is not None and not pending.future.cancelled():
            pending.kind = max(pending.kind, kind)
            self._outcomes[(kind.name.lower(), "coalesced")] += 1
            return pending.future
        self._waiting.pop(node_id, None)
        pending = Intent(node_id, kind, self.clock())
        self._waiting[node_id] = pending
        self._outcomes[(kind.name.lower(), "accepted")] += 1
        return pending.future

    def _dispatch(self) -> list[tuple[Future, BaseException]]:
        """Вызывается под lock; submit только в свободные slots, loader не вызывается."""
        failures: list[tuple[Future, BaseException]] = []
        if self._closed:
            return failures
        wave = ConfigWave(self.config_factory)
        for node_id in list(self._waiting):
            if len(self._active) >= self.concurrency:
                break
            if node_id in self._active or node_id in self._mutating:
                continue
            intent = self._waiting.pop(node_id)
            if intent.future.cancelled():
                continue
            self._active[node_id] = intent
            try:
                self.executor.submit(self._run, intent, wave)
            except Exception as exc:
                del self._active[node_id]
                self._outcomes[(intent.kind.name.lower(), "submit_failed")] += 1
                failures.append((intent.future, exc))
        return failures

    @staticmethod
    def _fail(failures: list[tuple[Future, BaseException]]) -> None:
        for future, error in failures:
            logger.warning("[node.operation] admission failed: %s", error)
            if not future.done():
                future.set_exception(error)

    def _run(self, intent: Intent, wave: ConfigWave) -> None:
        with self._lock:
            if self._active.get(intent.node_id) is not intent:
                return
            start = not intent.cancel_requested and intent.future.set_running_or_notify_cancel()
            intent.running = start
        result = None
        error: BaseException | None = None
        try:
            if start:
                result = self.execute(intent.node_id, intent.kind, wave.get)
        except BaseException as exc:
            error = exc
            logger.exception("[node.operation] node_id=%s kind=%s failed", intent.node_id, intent.kind.name)
        finally:
            with self._lock:
                if self._active.get(intent.node_id) is intent:
                    del self._active[intent.node_id]
                outcome = (
                    "cancelled" if not start else ("failed" if error is not None or result is False else "completed")
                )
                self._outcomes[(intent.kind.name.lower(), outcome)] += 1
                failures = self._dispatch()
            # Future callbacks may do arbitrary work; never invoke under scheduler lock.
            if start:
                if error is not None:
                    intent.future.set_exception(error)
                else:
                    intent.future.set_result(result)
            if not start:
                intent.future.cancel()
            self._fail(failures)

    def pending(self, node_id: int) -> bool:
        with self._lock:
            active = self._active.get(node_id)
            return node_id in self._waiting or (
                active is not None and not active.cancel_requested and not active.future.cancelled()
            )

    def cancel_pending(self, node_id: int) -> None:
        with self._lock:
            cancelled = self._cancel_queued(node_id)
            failures = self._dispatch()
        for future in cancelled:
            future.cancel()
        self._fail(failures)

    def _cancel_queued(self, node_id: int) -> list[Future]:
        cancelled = []
        waiting = self._waiting.pop(node_id, None)
        if waiting is not None:
            waiting.cancel_requested = True
            cancelled.append(waiting.future)
        active = self._active.get(node_id)
        if active is not None and not active.running:
            active.cancel_requested = True
            cancelled.append(active.future)
        return cancelled

    @contextmanager
    def mutation(self, node_id: int):
        with self._lock:
            active = self._active.get(node_id)
            if node_id in self._mutating or (active is not None and active.running):
                raise NodeBusyError()
            self._mutating.add(node_id)
            cancelled = self._cancel_queued(node_id)
            failures = self._dispatch()
        for future in cancelled:
            future.cancel()
        self._fail(failures)
        try:
            yield
        finally:
            with self._lock:
                self._mutating.discard(node_id)
                failures = self._dispatch()
            self._fail(failures)

    def snapshot(self) -> dict:
        with self._lock:
            oldest = min((intent.queued_at for intent in self._waiting.values()), default=self.clock())
            return {
                "active": len(self._active),
                "pending": len(self._waiting),
                "oldest_pending_seconds": max(0.0, self.clock() - oldest),
                "outcomes": dict(self._outcomes),
            }

    def shutdown(self, wait: bool = True) -> None:
        with self._lock:
            self._closed = True
            cancelled = []
            for node_id in set(self._waiting) | set(self._active):
                cancelled.extend(self._cancel_queued(node_id))
        for future in cancelled:
            future.cancel()
        self.executor.shutdown(wait=wait, cancel_futures=True)
        with self._lock:
            self._active = {node: intent for node, intent in self._active.items() if intent.running}
