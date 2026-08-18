"""Экспортер памяти процесса панели для Prometheus (NPVPN-1838).

Отвечает на вопрос «кто держит память» на двух дежурных уровнях:
RSS по процессам (сам python + дочерний xray) и именованные пробы известных
структур. Всё читается на скрейпе — фоновой работы нет, как в _DbPoolCollector.

Существующий /api/system отдаёт psutil.virtual_memory(), то есть память ХОСТА;
здесь речь именно о процессе.
"""

import gc
import tracemalloc
from collections.abc import Callable

import psutil
from prometheus_client import REGISTRY
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily

from app import logger

_process = psutil.Process()


def _probe_nodes():
    from app import xray

    return len(xray.nodes), None


def _probe_hosts(hosts=None):
    """Число тегов инбаундов в хранилище хостов.

    hosts — DictStorage: его keys()/values()/get() при пустом словаре вызывают
    update_func и идут в БД. Поэтому len() (не переопределён) и dict.values()
    несвязанным методом базового класса.
    """
    if hosts is None:
        from app import xray

        hosts = xray.hosts

    return len(hosts), None


def _probe_hosts_total(hosts=None):
    """Суммарное число хостов по всем тегам."""
    if hosts is None:
        from app import xray

        hosts = xray.hosts

    return sum(len(v) for v in dict.values(hosts)), None


def _probe_inbounds():
    from app import xray

    return len(xray.config.inbounds_by_tag), None


def _probe_node_json_cache():
    """Кэш пер-нодного JSON живёт не на модульном xray.config, а на копии конфига,
    которую делает include_db_users() под каждую волну переподключения (см.
    app/xray/config.py и app/xray/node_config.py). Слабую ссылку на кэш активной
    волны хранит сам node_config, специально для этой пробы.
    """
    from app.xray import node_config

    cache = node_config.get_current_node_json_cache()
    if cache is None:
        return None, None
    # Копия словаря, а не cache._cache напрямую и не под cache._lock: build под
    # этим локом длится секунды и исполняется на event loop, взятие лока
    # подвесило бы весь HTTP панели на время сборки. dict.copy() атомарна
    # относительно GIL.
    entries = cache._cache.copy()
    return len(entries), sum(len(v) for v in entries.values())


def _probe_node_json_cache_builds():
    """Кумулятивный счётчик билдов (не сбрасывается со сменой волны, в отличие от
    build_count на экземпляре кэша) — поэтому не зависит от того, жива ли текущая
    волна: репортит значение всегда, иначе метрика роста пропадала бы из графика
    в каждом промежутке между волнами.
    """
    from app.xray import node_config

    return node_config.get_node_json_cache_cumulative_builds(), None


def _probe_connecting_nodes():
    from app.xray import operations

    return len(operations._connecting_nodes), None


def _probe_connecting_started_at():
    from app.xray import operations

    return len(operations._connecting_started_at), None


def _probe_log_buffers():
    from app import xray

    return len(xray.core._temp_log_buffers), None


def _probe_logs_buffer():
    from app import xray

    return len(xray.core._logs_buffer), None


PROBES: dict[str, Callable[[], tuple[int | None, int | None]]] = {
    "xray.nodes": _probe_nodes,
    "xray.hosts": _probe_hosts,
    "xray.hosts.entries": _probe_hosts_total,
    "xray.config.inbounds": _probe_inbounds,
    "node_json_cache": _probe_node_json_cache,
    "node_json_cache.builds": _probe_node_json_cache_builds,
    "xray.connecting_nodes": _probe_connecting_nodes,
    "xray.connecting_started_at": _probe_connecting_started_at,
    "xray.core.log_buffers": _probe_log_buffers,
    "xray.core.logs_buffer": _probe_logs_buffer,
}


class _MemoryCollector:
    """Читает память процессов, статистику GC и пробы структур на каждом скрейпе."""

    def describe(self):
        # Без describe() prometheus_client вызывает collect() прямо при
        # регистрации — то есть на старте приложения, когда xray ещё не поднят.
        return []

    def collect(self):
        rss = GaugeMetricFamily(
            "panel_process_memory_rss_bytes",
            "Resident memory of the panel process and its children",
            labels=["process"],
        )
        vms = GaugeMetricFamily(
            "panel_process_memory_vms_bytes",
            "Virtual memory of the panel process and its children",
            labels=["process"],
        )
        try:
            info = _process.memory_info()
            rss.add_metric(["panel"], info.rss)
            vms.add_metric(["panel"], info.vms)
        except Exception as exc:
            logger.warning("[metrics] failed to read process memory: %s", exc)

        child_rss = 0
        child_vms = 0
        try:
            for child in _process.children(recursive=True):
                try:
                    child_info = child.memory_info()
                except psutil.Error:
                    continue
                child_rss += child_info.rss
                child_vms += child_info.vms
            rss.add_metric(["xray"], child_rss)
            vms.add_metric(["xray"], child_vms)
        except Exception as exc:
            logger.warning("[metrics] failed to read children memory: %s", exc)

        yield rss
        yield vms

        # panel_gc_*_total монотонно растут — Counter, а не Gauge. CounterMetricFamily
        # сам добавляет суффикс _total к имени, поэтому здесь имя передаётся без него:
        # иначе на выходе /metrics получится panel_gc_collections_total_total.
        collections = CounterMetricFamily(
            "panel_gc_collections", "GC collections per generation", labels=["generation"]
        )
        collected = CounterMetricFamily("panel_gc_collected", "Objects collected per generation", labels=["generation"])
        uncollectable = CounterMetricFamily(
            "panel_gc_uncollectable", "Uncollectable objects per generation", labels=["generation"]
        )
        try:
            for generation, stats in enumerate(gc.get_stats()):
                collections.add_metric([str(generation)], stats.get("collections", 0))
                collected.add_metric([str(generation)], stats.get("collected", 0))
                uncollectable.add_metric([str(generation)], stats.get("uncollectable", 0))
        except Exception as exc:
            logger.warning("[metrics] failed to read gc stats: %s", exc)

        yield collections
        yield collected
        yield uncollectable

        # Уровень 0 не управляется MEMORY_PROFILING_ENABLED — работает всегда, поэтому
        # именно здесь, а не за флагом, нужен признак «tracemalloc сейчас пишет трейсы»:
        # иначе забытый после инцидента trace/start (никто не позвал trace/stop) будет
        # держать overhead молча — и никто не узнает, что причина роста RSS не в утечке,
        # а в самом измерителе.
        tracing = GaugeMetricFamily(
            "panel_memory_tracing_enabled", "Whether tracemalloc is currently tracing allocations (1/0)"
        )
        try:
            tracing.add_metric([], 1 if tracemalloc.is_tracing() else 0)
        except Exception as exc:
            logger.warning("[metrics] failed to read tracemalloc state: %s", exc)

        yield tracing

        items = GaugeMetricFamily(
            "panel_memory_probe_items", "Number of elements held by a known structure", labels=["structure"]
        )
        sizes = GaugeMetricFamily(
            "panel_memory_probe_bytes", "Approximate bytes held by a known structure", labels=["structure"]
        )
        for name, probe in list(PROBES.items()):
            try:
                probe_items, probe_bytes = probe()
            except Exception as exc:
                # Диагностика не имеет права ронять скрейп: /metrics нужен
                # именно тогда, когда что-то уже сломалось.
                logger.warning("[metrics] memory probe %s failed: %s", name, exc)
                continue
            if probe_items is not None:
                items.add_metric([name], probe_items)
            if probe_bytes is not None:
                sizes.add_metric([name], probe_bytes)

        yield items
        yield sizes


_registered = False


def register():
    global _registered
    if _registered:
        return
    try:
        REGISTRY.register(_MemoryCollector())
        _registered = True
    except Exception as exc:
        logger.warning("[metrics] failed to register memory collector: %s", exc)
