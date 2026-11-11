"""Миграция жёсткой заглушки: значение первого бота, остальные ключи на месте."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

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
    enabled_first = [
        (2, {"sub_device_limit_hard_mode": False}),
        (1, {"sub_device_limit_hard_mode": True, "show_ads": False}),
    ]
    assert module.pick_hard_mode(enabled_first) is True


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


class _Op:
    def __init__(self, bind):
        self._bind = bind

    def get_bind(self):
        return self._bind


def test_upgrade_copies_enabled_flag_from_lowest_bot_and_keeps_panel_keys(monkeypatch):
    module = _module()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE bots (id INTEGER PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE bot_settings (bot_id INTEGER PRIMARY KEY, data TEXT)"))
        conn.execute(
            text(
                "CREATE TABLE global_settings ("
                '"key" VARCHAR(64) PRIMARY KEY, data TEXT, created_at DATETIME, updated_at DATETIME)'
            )
        )
        conn.execute(text("INSERT INTO bots (id) VALUES (1), (2)"))
        conn.execute(
            text("INSERT INTO bot_settings (bot_id, data) VALUES (:bot_id, :data)"),
            [
                {"bot_id": 2, "data": json.dumps({"sub_device_limit_hard_mode": False, "show_ads": True})},
                {"bot_id": 1, "data": json.dumps({"sub_device_limit_hard_mode": True, "show_ads": False})},
            ],
        )
        conn.execute(
            text(
                'INSERT INTO global_settings ("key", data, created_at, updated_at) '
                "VALUES ('panel', :data, '2026-01-01', '2026-01-01')"
            ),
            {"data": json.dumps({"bs_monthly_limit": 10})},
        )
        monkeypatch.setattr(module, "op", _Op(conn))
        module.upgrade()

        panel = json.loads(conn.execute(text("SELECT data FROM global_settings WHERE \"key\" = 'panel'")).scalar())
        assert panel["bs_monthly_limit"] == 10
        assert panel["sub_device_limit_hard_mode"] is True
        first = json.loads(conn.execute(text("SELECT data FROM bot_settings WHERE bot_id = 1")).scalar())
        second = json.loads(conn.execute(text("SELECT data FROM bot_settings WHERE bot_id = 2")).scalar())
        assert "sub_device_limit_hard_mode" not in first
        assert first["show_ads"] is False
        assert "sub_device_limit_hard_mode" not in second
        assert second["show_ads"] is True
