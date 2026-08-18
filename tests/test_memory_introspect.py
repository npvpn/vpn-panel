"""Тесты диагностики памяти по требованию (NPVPN-1838)."""

import tracemalloc

import pytest

from app.utils import memory_introspect


@pytest.fixture(autouse=True)
def _stop_tracing():
    yield
    if tracemalloc.is_tracing():
        tracemalloc.stop()
    memory_introspect._baseline = None


def test_heap_snapshot_reports_types():
    result = memory_introspect.heap_snapshot(top=5)

    assert result["total_objects"] > 0
    assert len(result["top_by_count"]) <= 5
    entry = result["top_by_count"][0]
    assert set(entry) == {"type", "count", "bytes"}
    assert entry["count"] > 0


def test_heap_snapshot_reports_top_by_bytes():
    """Тип с горсткой огромных объектов не попал бы в top_by_count, но обязан
    появиться в top_by_bytes — ради этого случая и нужен уровень 2."""

    class _HugeBallast:
        def __init__(self):
            self.payload = "z" * (2 * 1024 * 1024)

    ballast = [_HugeBallast() for _ in range(3)]

    result = memory_introspect.heap_snapshot(top=2000)

    # __qualname__ включает путь вложенности (test_.....<locals>._HugeBallast).
    by_bytes = {entry["type"]: entry for entry in result["top_by_bytes"]}
    matches = [entry for name, entry in by_bytes.items() if name.endswith("_HugeBallast")]
    assert matches, by_bytes.keys()
    entry = matches[0]
    assert entry["count"] == 3
    assert entry["bytes"] > 0
    del ballast


def test_heap_snapshot_clamps_top():
    result = memory_introspect.heap_snapshot(top=-5)
    assert len(result["top_by_count"]) <= 1

    result = memory_introspect.heap_snapshot(top=10**9)
    assert len(result["top_by_count"]) <= 500


def test_heap_snapshot_rejects_parallel_scan():
    memory_introspect._scan_lock.acquire()
    try:
        with pytest.raises(memory_introspect.HeapScanBusy):
            memory_introspect.heap_snapshot(top=5)
    finally:
        memory_introspect._scan_lock.release()


def test_trace_snapshot_requires_started_tracing():
    with pytest.raises(memory_introspect.TracingNotStarted):
        memory_introspect.trace_snapshot(top=5)


def test_trace_start_snapshot_stop_cycle():
    started = memory_introspect.trace_start(nframes=1)
    assert started["started"] is True
    assert tracemalloc.is_tracing()

    ballast = ["x" * 1024 for _ in range(1000)]

    snapshot = memory_introspect.trace_snapshot(top=5)
    assert snapshot["tracing"] is True
    assert snapshot["top"]
    assert set(snapshot["top"][0]) == {"location", "size_bytes", "count"}

    assert len(ballast) == 1000

    stopped = memory_introspect.trace_stop()
    assert stopped["stopped"] is True
    assert not tracemalloc.is_tracing()


def test_trace_snapshot_reports_delta_after_first_call():
    """Дельта не просто непустая (compare_to почти всегда что-то отдаёт), а содержит
    запись с положительным size_diff в строке, где выделен балласт — иначе тест
    не поймает регресс, при котором дельта считается неправильно."""
    memory_introspect.trace_start(nframes=1)
    memory_introspect.trace_snapshot(top=50)

    ballast = ["y" * 2048 for _ in range(1000)]  # noqa: F841 — аллокация нужна как есть

    second = memory_introspect.trace_snapshot(top=50)
    assert second["delta"]
    this_file = __file__
    matching = [entry for entry in second["delta"] if this_file in entry["location"] and entry["size_bytes"] > 0]
    assert matching, second["delta"]


def test_trace_snapshot_clamps_top():
    memory_introspect.trace_start(nframes=1)

    snapshot = memory_introspect.trace_snapshot(top=-5)
    assert len(snapshot["top"]) <= 1


def test_trace_stop_without_start_is_noop():
    assert memory_introspect.trace_stop() == {"stopped": False}


def test_trace_start_reports_actual_depth_when_already_tracing():
    memory_introspect.trace_start(nframes=1)
    assert tracemalloc.get_traceback_limit() == 1

    restarted = memory_introspect.trace_start(nframes=5)

    assert restarted["nframes"] == tracemalloc.get_traceback_limit()
    assert restarted["nframes"] == 1
