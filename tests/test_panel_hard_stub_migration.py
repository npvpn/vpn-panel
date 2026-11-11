"""Миграция жёсткой заглушки: значение первого бота, остальные ключи на месте."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

_VERSIONS = Path(__file__).resolve().parents[1] / "app/db/migrations/versions"


def _module() -> ModuleType:
    matches = list(_VERSIONS.glob("*npvpn_2365_panel_hard_stub.py"))
    assert len(matches) == 1, matches
    spec = importlib.util.spec_from_file_location("npvpn_2365_panel_hard_stub", matches[0])
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pick_uses_lowest_bot_id_not_the_other_bot():
    module = _module()
    rows = [
        (2, {"sub_device_limit_hard_mode": True}),
        (1, {"sub_device_limit_hard_mode": False}),
    ]
    assert module.pick_hard_mode(rows) is False


def test_pick_without_bots_is_false():
    module = _module()
    assert module.pick_hard_mode([]) is False


def test_pick_missing_key_is_false():
    module = _module()
    assert module.pick_hard_mode([(1, {"show_ads": True})]) is False


def test_strip_removes_only_hard_mode():
    module = _module()
    payload = {"sub_device_limit_hard_mode": True, "show_ads": False}
    assert module.strip_hard_mode(payload) == {"show_ads": False}
