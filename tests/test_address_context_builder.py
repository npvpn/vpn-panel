"""build_address_context: сборка контекста + наблюдаемость пустого снимка весов (NPVPN-2072)."""

from __future__ import annotations

import logging
import sys
import types
from dataclasses import dataclass

for _name, _module in list(sys.modules.items()):
    if _name.startswith("app.") and not hasattr(_module, "__file__") and not hasattr(_module, "__path__"):
        del sys.modules[_name]

_share_stub = types.ModuleType("app.subscription.share")
_share_stub.generate_v2ray_links = lambda *args, **kwargs: []
sys.modules.setdefault("app.subscription.share", _share_stub)

from app.db import crud  # noqa: E402
from app.subscription.address_context_builder import build_address_context  # noqa: E402

if sys.modules.get("app.subscription.share") is _share_stub:
    del sys.modules["app.subscription.share"]


@dataclass
class _StubUser:
    id: int
    address_rotation_offset: int = 0


BOT_SETTINGS = {
    "sub_address_subset_enabled": True,
    "sub_address_subset_size": 2,
    "sub_address_rotation_days": 2,
}


def test_disabled_flag_short_circuits_without_touching_weights(monkeypatch):
    called = False

    def fake_get_weight_snapshot(*args, **kwargs):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(crud, "get_weight_snapshot", fake_get_weight_snapshot)
    monkeypatch.setattr(crud, "get_active_pins", lambda *a, **k: {})
    ctx = build_address_context(
        None, _StubUser(id=1), is_revoked=False, is_expired=False, bot_settings={"sub_address_subset_enabled": False}
    )
    assert ctx.enabled is False
    assert called is False


def test_disabled_flag_still_queries_pins_exactly_once(monkeypatch):
    """Закрепление должно работать и при выключенной фиче — но не ценой лишних
    запросов: один дешёвый индексный запрос на рендер, не больше."""
    calls = 0

    def fake_get_active_pins(*args, **kwargs):
        nonlocal calls
        calls += 1
        return {}

    monkeypatch.setattr(crud, "get_weight_snapshot", lambda *a, **k: {})
    monkeypatch.setattr(crud, "get_active_pins", fake_get_active_pins)
    build_address_context(
        None, _StubUser(id=1), is_revoked=False, is_expired=False, bot_settings={"sub_address_subset_enabled": False}
    )
    assert calls == 1


def test_pin_applies_when_subset_flag_disabled():
    """Закрепление — явное ручное действие саппорта/отладки, оно не должно
    глохнуть от выключенного флага автовыбора: иначе инструмент бесполезен
    именно там, где нужен — пока фича ещё не раскатана."""
    from app.subscription.address_context import AddressContext

    ADDRESSES = ["1.1.1.1", "2.2.2.2", "3.3.3.3", "4.4.4.4"]
    NODE_IDS = [11, 22, 33, 44]

    ctx = AddressContext(user_id=1, size=0, epoch=0, weights={}, enabled=False, pins={9: [33]})
    picked = ctx.pick(ADDRESSES, NODE_IDS, addresses_from_nodes=True, host_id=9)
    assert picked == ["3.3.3.3"]


def test_disabled_flag_without_pins_unchanged(monkeypatch):
    """Фича выключена и пинов нет: выдача ровно прежняя, побайтово."""
    ADDRESSES = ["1.1.1.1", "2.2.2.2", "3.3.3.3", "4.4.4.4"]
    NODE_IDS = [11, 22, 33, 44]

    monkeypatch.setattr(crud, "get_weight_snapshot", lambda *a, **k: {})
    monkeypatch.setattr(crud, "get_active_pins", lambda *a, **k: {})
    ctx = build_address_context(
        None, _StubUser(id=1), is_revoked=False, is_expired=False, bot_settings={"sub_address_subset_enabled": False}
    )
    assert ctx.pick(ADDRESSES, NODE_IDS, addresses_from_nodes=True, host_id=9) == ADDRESSES


def test_revoked_or_expired_disables_regardless_of_flag(monkeypatch):
    monkeypatch.setattr(crud, "get_weight_snapshot", lambda *a, **k: {1: 100.0})
    assert (
        build_address_context(
            None, _StubUser(id=1), is_revoked=True, is_expired=False, bot_settings=BOT_SETTINGS
        ).enabled
        is False
    )
    assert (
        build_address_context(
            None, _StubUser(id=1), is_revoked=False, is_expired=True, bot_settings=BOT_SETTINGS
        ).enabled
        is False
    )


def test_enabled_context_carries_weights_through(monkeypatch):
    monkeypatch.setattr(crud, "get_weight_snapshot", lambda *a, **k: {5: 300.0})
    monkeypatch.setattr(crud, "get_active_pins", lambda *a, **k: {})
    ctx = build_address_context(None, _StubUser(id=1), is_revoked=False, is_expired=False, bot_settings=BOT_SETTINGS)
    assert ctx.enabled is True
    assert ctx.weights == {5: 300.0}


def test_warns_when_enabled_but_snapshot_empty(monkeypatch, caplog):
    monkeypatch.setattr(crud, "get_weight_snapshot", lambda *a, **k: {})
    monkeypatch.setattr(crud, "get_active_pins", lambda *a, **k: {})
    with caplog.at_level(logging.WARNING, logger="app.subscription.address_context_builder"):
        build_address_context(None, _StubUser(id=7), is_revoked=False, is_expired=False, bot_settings=BOT_SETTINGS)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "weight snapshot is empty" in warnings[0].getMessage()


def test_no_warning_when_snapshot_present(monkeypatch, caplog):
    monkeypatch.setattr(crud, "get_weight_snapshot", lambda *a, **k: {5: 100.0})
    monkeypatch.setattr(crud, "get_active_pins", lambda *a, **k: {})
    with caplog.at_level(logging.WARNING, logger="app.subscription.address_context_builder"):
        build_address_context(None, _StubUser(id=7), is_revoked=False, is_expired=False, bot_settings=BOT_SETTINGS)

    assert caplog.records == []


def test_pins_carry_through(monkeypatch):
    monkeypatch.setattr(crud, "get_weight_snapshot", lambda *a, **k: {5: 300.0})
    monkeypatch.setattr(crud, "get_active_pins", lambda *a, **k: {9: [1, 2]})
    ctx = build_address_context(None, _StubUser(id=1), is_revoked=False, is_expired=False, bot_settings=BOT_SETTINGS)
    assert ctx.pins == {9: [1, 2]}
