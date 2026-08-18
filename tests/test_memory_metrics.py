"""Тесты экспортера памяти панели (NPVPN-1838)."""

import tracemalloc

from app.utils import memory_metrics


def _collect(collector):
    return {m.name: m for m in collector.collect()}


def test_process_metrics_are_exported():
    collector = memory_metrics._MemoryCollector()
    families = _collect(collector)

    rss = families["panel_process_memory_rss_bytes"]
    processes = {tuple(s.labels.values()) for s in rss.samples}
    assert ("panel",) in processes
    assert all(s.value >= 0 for s in rss.samples)


def _samples_by_name(collector):
    samples = {}
    for family in collector.collect():
        for sample in family.samples:
            samples.setdefault(sample.name, []).append(sample)
    return samples


def test_gc_metrics_are_exported():
    """gc-метрики — Counter (не Gauge): монотонно растут. CounterMetricFamily сам
    добавляет суффикс _total, поэтому здесь сверяется итоговое имя сэмпла на выходе
    /metrics, а не имя семейства (у него суффикса нет)."""
    collector = memory_metrics._MemoryCollector()
    samples = _samples_by_name(collector)

    collections = samples["panel_gc_collections_total"]
    generations = {s.labels["generation"] for s in collections}
    assert generations == {"0", "1", "2"}


def test_gc_metrics_are_counters_not_gauges():
    """Регресс-тест на пункт 5 ревью: имена семплов не должны разъехаться при
    смене GaugeMetricFamily -> CounterMetricFamily (двойной суффикс _total_total
    или его отсутствие — оба варианта сломали бы Grafana-дашборд и запросы)."""
    collector = memory_metrics._MemoryCollector()
    samples = _samples_by_name(collector)

    for name in ("panel_gc_collections_total", "panel_gc_collected_total", "panel_gc_uncollectable_total"):
        assert name in samples
        assert f"{name}_total" not in samples


def test_probe_values_are_exported(monkeypatch):
    monkeypatch.setitem(memory_metrics.PROBES, "fake.structure", lambda: (7, 1024))

    families = _collect(memory_metrics._MemoryCollector())

    items = {s.labels["structure"]: s.value for s in families["panel_memory_probe_items"].samples}
    sizes = {s.labels["structure"]: s.value for s in families["panel_memory_probe_bytes"].samples}
    assert items["fake.structure"] == 7
    assert sizes["fake.structure"] == 1024


def test_probe_without_bytes_emits_only_items(monkeypatch):
    monkeypatch.setitem(memory_metrics.PROBES, "items.only", lambda: (3, None))

    families = _collect(memory_metrics._MemoryCollector())

    items = {s.labels["structure"]: s.value for s in families["panel_memory_probe_items"].samples}
    sizes = {s.labels["structure"] for s in families["panel_memory_probe_bytes"].samples}
    assert items["items.only"] == 3
    assert "items.only" not in sizes


def test_failing_probe_does_not_break_scrape(monkeypatch):
    def boom():
        raise RuntimeError("structure renamed")

    monkeypatch.setitem(memory_metrics.PROBES, "broken", boom)
    monkeypatch.setitem(memory_metrics.PROBES, "healthy", lambda: (1, None))

    families = _collect(memory_metrics._MemoryCollector())

    items = {s.labels["structure"]: s.value for s in families["panel_memory_probe_items"].samples}
    assert items["healthy"] == 1
    assert "broken" not in items


def test_tracing_gauge_reflects_state_when_not_tracing():
    assert not tracemalloc.is_tracing()

    families = _collect(memory_metrics._MemoryCollector())

    gauge = families["panel_memory_tracing_enabled"]
    assert [s.value for s in gauge.samples] == [0]


def test_tracing_gauge_reflects_state_when_tracing():
    tracemalloc.start()
    try:
        families = _collect(memory_metrics._MemoryCollector())
        gauge = families["panel_memory_tracing_enabled"]
        assert [s.value for s in gauge.samples] == [1]
    finally:
        tracemalloc.stop()

    assert not tracemalloc.is_tracing()


def test_node_json_cache_probes_read_live_wave_cache():
    """Регресс на CRITICAL-находку: раньше пробы читали getattr(xray.config,
    "_node_json_cache", None), где кэша никогда не было (он живёт на копии
    конфига волны, а не на модульном xray.config). Теперь читают через
    node_config.get_current_node_json_cache()."""
    from app.xray import node_config

    cache = node_config._NodeJsonCache(base_config=object(), build=lambda *a, **kw: "x" * 10)
    cache.get(["TAG"], {}, [])

    items, size_bytes = memory_metrics._probe_node_json_cache()
    assert items == 1
    assert size_bytes == 10

    builds, _ = memory_metrics._probe_node_json_cache_builds()
    assert builds >= 1


def test_node_json_cache_probe_is_none_without_live_cache(monkeypatch):
    from app.xray import node_config

    monkeypatch.setattr(node_config, "_current_cache_ref", None)

    items, size_bytes = memory_metrics._probe_node_json_cache()
    assert items is None
    assert size_bytes is None


def test_node_json_cache_probe_does_not_pin_dead_cache():
    """Слабая ссылка: когда кэш волны собран GC, проба не эмитит метрику вместо
    того, чтобы держать полную копию конфига в памяти вечно."""
    import gc

    from app.xray import node_config

    def _make_and_drop():
        node_config._NodeJsonCache(base_config=object(), build=lambda *a, **kw: "x")

    _make_and_drop()
    gc.collect()

    assert node_config.get_current_node_json_cache() is None
    items, size_bytes = memory_metrics._probe_node_json_cache()
    assert items is None
    assert size_bytes is None


def test_hosts_probe_does_not_trigger_db_update():
    """DictStorage.values()/keys() при пустом storage лезут в БД.

    Проба обязана читать хосты в обход этого — иначе каждый скрейп Prometheus
    оборачивается запросом в MySQL.
    """
    from app.utils.store import DictStorage

    calls = []

    def update_func(storage):
        calls.append(1)
        storage["INBOUND"] = [{"remark": "x"}]

    hosts = DictStorage(update_func)

    items, _ = memory_metrics._probe_hosts(hosts)

    assert calls == []
    assert items == 0


def test_register_is_idempotent(monkeypatch):
    """Второй register() не должен трогать глобальный REGISTRY.

    Мокаем сам REGISTRY.register: реальная повторная регистрация подняла бы
    ValueError про дублирующиеся имена метрик, и тест проверял бы обработку
    ошибки вместо идемпотентности.
    """
    calls = []
    monkeypatch.setattr(memory_metrics.REGISTRY, "register", calls.append)
    monkeypatch.setattr(memory_metrics, "_registered", False)

    memory_metrics.register()
    memory_metrics.register()

    assert len(calls) == 1


def test_collector_describe_is_empty():
    """describe() должен быть пустым: иначе prometheus_client вызовет collect()
    прямо в момент регистрации на старте приложения, когда xray ещё не поднят."""
    assert list(memory_metrics._MemoryCollector().describe()) == []
