"""build_address_context: сборка контекста + наблюдаемость пустого снимка весов (NPVPN-2072)."""

from __future__ import annotations

import logging
import sys
import types
from dataclasses import dataclass

import pytest

for _name, _module in list(sys.modules.items()):
    if _name.startswith("app.") and not hasattr(_module, "__file__") and not hasattr(_module, "__path__"):
        del sys.modules[_name]

_share_stub = types.ModuleType("app.subscription.share")
_share_stub.generate_v2ray_links = lambda *args, **kwargs: []
sys.modules.setdefault("app.subscription.share", _share_stub)

from app.db import crud  # noqa: E402
from app.subscription.address_context_builder import (  # noqa: E402
    build_address_context,
    get_exhausted_nodes,
    reset_exhausted_cache,
)

if sys.modules.get("app.subscription.share") is _share_stub:
    del sys.modules["app.subscription.share"]


@dataclass
class _StubUser:
    id: int
    address_rotation_offset: int = 0


# Периоды ротации включённых хостов: настройка живёт на хосте (NPVPN-2072), поэтому
# сборщик контекста получает именно их, а не настройки бота.
PERIODS = {2}
NO_PERIODS: set[int] = set()


def build(user_id=1, *, is_revoked=False, is_expired=False, rotation_periods=PERIODS):
    return build_address_context(
        None,
        _StubUser(id=user_id),
        is_revoked=is_revoked,
        is_expired=is_expired,
        rotation_periods=rotation_periods,
    )


@pytest.fixture(autouse=True)
def _no_exhausted(monkeypatch):
    """Порог исчерпания живёт своим тестом; здесь он не должен ходить в БД."""
    monkeypatch.setattr(crud, "get_exhausted_node_ids", lambda *a, **k: frozenset())
    reset_exhausted_cache()
    yield
    reset_exhausted_cache()


def test_no_enabled_hosts_short_circuits_without_touching_weights(monkeypatch):
    """Ни один хост не сужает — за весами в БД не ходим вовсе."""
    called = False

    def fake_get_weight_snapshot(*args, **kwargs):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(crud, "get_weight_snapshot", fake_get_weight_snapshot)
    monkeypatch.setattr(crud, "get_active_pins", lambda *a, **k: {})
    ctx = build(rotation_periods=NO_PERIODS)
    assert ctx.weights_by_day == {}
    assert called is False


def test_no_enabled_hosts_still_queries_pins_exactly_once(monkeypatch):
    """Закрепление должно работать и при выключенной фиче — но не ценой лишних
    запросов: один дешёвый индексный запрос на рендер, не больше."""
    calls = 0

    def fake_get_active_pins(*args, **kwargs):
        nonlocal calls
        calls += 1
        return {}

    monkeypatch.setattr(crud, "get_weight_snapshot", lambda *a, **k: {})
    monkeypatch.setattr(crud, "get_active_pins", fake_get_active_pins)
    build(rotation_periods=NO_PERIODS)
    assert calls == 1


def test_pin_applies_when_host_subset_disabled(monkeypatch):
    """Закрепление — явное ручное действие саппорта/отладки, оно не должно
    глохнуть от выключенного на хосте сужения: иначе инструмент бесполезен
    именно там, где нужен — пока фича ещё не раскатана."""
    ADDRESSES = ["1.1.1.1", "2.2.2.2", "3.3.3.3", "4.4.4.4"]
    NODE_IDS = [11, 22, 33, 44]

    monkeypatch.setattr(crud, "get_weight_snapshot", lambda *a, **k: {})
    monkeypatch.setattr(crud, "get_active_pins", lambda *a, **k: {9: [33]})
    ctx = build(rotation_periods=NO_PERIODS)
    picked = ctx.pick(ADDRESSES, NODE_IDS, addresses_from_nodes=True, host_id=9)
    assert picked == ["3.3.3.3"]


def test_no_enabled_hosts_without_pins_unchanged(monkeypatch):
    """Сужение нигде не включено и пинов нет: выдача ровно прежняя, побайтово."""
    ADDRESSES = ["1.1.1.1", "2.2.2.2", "3.3.3.3", "4.4.4.4"]
    NODE_IDS = [11, 22, 33, 44]

    monkeypatch.setattr(crud, "get_weight_snapshot", lambda *a, **k: {})
    monkeypatch.setattr(crud, "get_active_pins", lambda *a, **k: {})
    ctx = build(rotation_periods=NO_PERIODS)
    # settings по умолчанию — «хост не сужает»: ровно то, что придёт из settings_from_host
    # для хоста с выключенной настройкой.
    assert ctx.pick(ADDRESSES, NODE_IDS, addresses_from_nodes=True, host_id=9) == ADDRESSES


def test_revoked_or_expired_disables_regardless_of_hosts(monkeypatch):
    monkeypatch.setattr(crud, "get_weight_snapshot", lambda *a, **k: {1: 100.0})
    assert build(is_revoked=True).enabled is False
    assert build(is_expired=True).enabled is False


def test_enabled_context_carries_weights_through(monkeypatch):
    monkeypatch.setattr(crud, "get_weight_snapshot", lambda *a, **k: {5: 300.0})
    monkeypatch.setattr(crud, "get_active_pins", lambda *a, **k: {})
    ctx = build()
    assert ctx.enabled is True
    assert list(ctx.weights_by_day.values()) == [{5: 300.0}]


def test_one_snapshot_per_distinct_period(monkeypatch):
    """Хосты с разными периодами берут снимки на разные сутки — по одному запросу на день."""
    days: list[int] = []

    def fake_snapshot(_db, day):
        days.append(day)
        return {5: 300.0}

    monkeypatch.setattr(crud, "get_weight_snapshot", fake_snapshot)
    monkeypatch.setattr(crud, "get_active_pins", lambda *a, **k: {})
    ctx = build(rotation_periods={1, 2, 7})
    assert len(days) == len(set(days)), "один день — один запрос"
    assert set(ctx.weights_by_day) == set(days)


def test_warns_when_enabled_but_snapshot_empty(monkeypatch, caplog):
    monkeypatch.setattr(crud, "get_weight_snapshot", lambda *a, **k: {})
    monkeypatch.setattr(crud, "get_active_pins", lambda *a, **k: {})
    with caplog.at_level(logging.WARNING, logger="app.subscription.address_context_builder"):
        build(user_id=7)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "weight snapshot is empty" in warnings[0].getMessage()


def test_no_warning_when_snapshot_present(monkeypatch, caplog):
    monkeypatch.setattr(crud, "get_weight_snapshot", lambda *a, **k: {5: 100.0})
    monkeypatch.setattr(crud, "get_active_pins", lambda *a, **k: {})
    with caplog.at_level(logging.WARNING, logger="app.subscription.address_context_builder"):
        build(user_id=7)

    assert caplog.records == []


def test_pins_carry_through(monkeypatch):
    monkeypatch.setattr(crud, "get_weight_snapshot", lambda *a, **k: {5: 300.0})
    monkeypatch.setattr(crud, "get_active_pins", lambda *a, **k: {9: [1, 2]})
    assert build().pins == {9: [1, 2]}


def test_exhausted_nodes_are_cached_between_renders(monkeypatch):
    """Рендер подписки горячий: список исчерпанных нод не должен стоить запроса каждый раз."""
    calls = 0

    def fake_exhausted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return frozenset({3})

    monkeypatch.setattr(crud, "get_weight_snapshot", lambda *a, **k: {5: 300.0})
    monkeypatch.setattr(crud, "get_active_pins", lambda *a, **k: {})
    monkeypatch.setattr(crud, "get_exhausted_node_ids", fake_exhausted)
    reset_exhausted_cache()

    assert build().exhausted == frozenset({3})
    assert build(user_id=2).exhausted == frozenset({3})
    assert calls == 1


def test_exhausted_cache_expires(monkeypatch):
    """TTL истёк — данные перечитываются: порог обязан реагировать в пределах минуты."""
    import app.subscription.address_context_builder as builder

    calls = 0

    def fake_exhausted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return frozenset({calls})

    monkeypatch.setattr(crud, "get_exhausted_node_ids", fake_exhausted)
    monkeypatch.setattr(builder, "_EXHAUSTED_TTL_SECONDS", 0)
    reset_exhausted_cache()

    assert get_exhausted_nodes(None) == frozenset({1})
    assert get_exhausted_nodes(None) == frozenset({2})
    assert calls == 2
