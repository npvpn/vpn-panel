"""Диагностика памяти по требованию: срез кучи и tracemalloc (NPVPN-1838).

Оба инструмента платные по CPU, поэтому вызываются только явно и живут за
env-флагом MEMORY_PROFILING_ENABLED. Логика отделена от роутера: тесты панели
не поднимают FastAPI-приложение.
"""

import gc
import sys
import threading
import tracemalloc
from collections import Counter

_scan_lock = threading.Lock()
_baseline = None


class HeapScanBusy(Exception):
    """Скан кучи уже выполняется."""


class TracingNotStarted(Exception):
    """tracemalloc не запущен."""


def heap_snapshot(top: int = 30) -> dict:
    """Срез живых объектов по типам.

    Обходит всю кучу и держит GIL на время обхода — отсюда лок: два
    параллельных скана удвоят паузу без всякой пользы.

    Отдаёт топ по числу объектов (`top_by_count`) и отдельно топ по суммарным байтам
    (`top_by_bytes`): тип с горсткой гигантских объектов (один список на 500 МБ) в
    первый топ может не попасть вовсе, а это ровно тот случай, ради которого нужен
    срез кучи.
    """
    top = max(1, min(int(top), 500))
    if not _scan_lock.acquire(blocking=False):
        raise HeapScanBusy

    try:
        objects = gc.get_objects()
        counts: Counter[str] = Counter()
        sizes: Counter[str] = Counter()
        for obj in objects:
            name = type(obj).__qualname__
            counts[name] += 1
            try:
                sizes[name] += sys.getsizeof(obj)
            except Exception:
                continue

        total = len(objects)
        del objects

        return {
            "total_objects": total,
            "top_by_count": [
                {"type": name, "count": count, "bytes": sizes[name]} for name, count in counts.most_common(top)
            ],
            "top_by_bytes": [
                {"type": name, "count": counts[name], "bytes": size} for name, size in sizes.most_common(top)
            ],
        }
    finally:
        _scan_lock.release()


def trace_start(nframes: int = 1) -> dict:
    """Запускает трейсинг аллокаций.

    Видит только то, что аллоцировано после старта — для вопроса «что растёт»
    это и нужно, а рестарт панели ради полной картины не оправдан.

    Если трейсинг уже запущен, повторный `tracemalloc.start(nframes)` не меняет
    действующую глубину трейсбека (эмпирически подтверждено: `get_traceback_limit()`
    остаётся прежним). Поэтому в ответе всегда фактическая глубина
    (`tracemalloc.get_traceback_limit()`), а не запрошенная — иначе вызывающий
    получит цифру, которой в процессе нет.
    """
    global _baseline

    nframes = max(1, min(int(nframes), 10))
    if not tracemalloc.is_tracing():
        tracemalloc.start(nframes)
    _baseline = tracemalloc.take_snapshot()
    return {"started": True, "nframes": tracemalloc.get_traceback_limit()}


def trace_snapshot(top: int = 30) -> dict:
    """Топ мест аллокации и дельта к предыдущему снимку."""
    global _baseline

    if not tracemalloc.is_tracing():
        raise TracingNotStarted

    top = max(1, min(int(top), 500))
    snapshot = tracemalloc.take_snapshot()
    statistics = snapshot.statistics("lineno")[:top]
    result = {
        "tracing": True,
        "top": [{"location": str(stat.traceback), "size_bytes": stat.size, "count": stat.count} for stat in statistics],
        "delta": [],
    }

    if _baseline is not None:
        delta = snapshot.compare_to(_baseline, "lineno")[:top]
        result["delta"] = [
            {"location": str(stat.traceback), "size_bytes": stat.size_diff, "count": stat.count_diff} for stat in delta
        ]

    _baseline = snapshot
    return result


def trace_stop() -> dict:
    """Останавливает трейсинг и освобождает накопленные трейсы."""
    global _baseline

    if not tracemalloc.is_tracing():
        return {"stopped": False}

    tracemalloc.stop()
    _baseline = None
    return {"stopped": True}
