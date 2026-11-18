"""Параллельный первый доступ использует один пул статистики."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock


def test_concurrent_first_access_returns_one_executor(monkeypatch):
    """Одновременные usage jobs не удваивают предел worker-ов."""
    from app.utils import concurrency

    created, instances = [], []
    release, doubled = threading.Event(), threading.Event()
    lock = threading.Lock()
    barrier = threading.Barrier(3)
    if hasattr(concurrency.get_usage_executor, "cache_clear"):
        concurrency.get_usage_executor.cache_clear()

    def create(**_kwargs):
        instance = Mock()
        with lock:
            created.append(instance)
            if len(created) > 1:
                doubled.set()
        assert release.wait(2)
        return instance

    monkeypatch.setattr(concurrency, "ThreadPoolExecutor", create)

    def get():
        barrier.wait()
        instances.append(concurrency.get_usage_executor())

    with ThreadPoolExecutor(max_workers=2) as callers:
        first, second = callers.submit(get), callers.submit(get)
        barrier.wait()
        try:
            doubled.wait(0.2)
        finally:
            release.set()
        first.result(timeout=2)
        second.result(timeout=2)
    assert instances[0] is instances[1]
