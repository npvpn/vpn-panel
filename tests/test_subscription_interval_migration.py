"""Интервал обновления профиля становится общей настройкой панели."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

_VERSIONS = Path(__file__).resolve().parents[1] / "app/db/migrations/versions"


def _module() -> ModuleType:
    matches = list(_VERSIONS.glob("*npvpn_2244_move_profile_interval_to_panel.py"))
    assert len(matches) == 1, matches
    spec = importlib.util.spec_from_file_location("subscription_interval_migration", matches[0])
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Op:
    def __init__(self, bind):
        self._bind = bind

    def get_bind(self):
        return self._bind


def _engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE bot_settings (bot_id INTEGER PRIMARY KEY, data TEXT)"))
        conn.execute(
            text(
                "CREATE TABLE global_settings ("
                '"key" VARCHAR(64) PRIMARY KEY, data TEXT, created_at DATETIME, updated_at DATETIME)'
            )
        )
    return engine


def test_upgrade_sets_one_hour_on_panel_and_strips_every_bot(monkeypatch):
    migration = _module()
    engine = _engine()
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO bot_settings (bot_id, data) VALUES (:bot_id, :data)"),
            [
                {"bot_id": 1, "data": json.dumps({"sub_update_interval": "24", "show_ads": False})},
                {"bot_id": 2, "data": json.dumps({"sub_update_interval": "6", "web_url": "https://cab"})},
            ],
        )
        conn.execute(
            text(
                'INSERT INTO global_settings ("key", data, created_at, updated_at) '
                "VALUES ('panel', :data, '2026-01-01', '2026-01-01')"
            ),
            {"data": json.dumps({"bs_monthly_limit": 10})},
        )
        monkeypatch.setattr(migration, "op", _Op(conn))
        migration.upgrade()

        panel = json.loads(conn.execute(text("SELECT data FROM global_settings WHERE \"key\" = 'panel'")).scalar())
        assert panel == {"bs_monthly_limit": 10, "sub_update_interval": "1"}
        first = json.loads(conn.execute(text("SELECT data FROM bot_settings WHERE bot_id = 1")).scalar())
        second = json.loads(conn.execute(text("SELECT data FROM bot_settings WHERE bot_id = 2")).scalar())
        assert first == {"show_ads": False}
        assert second == {"web_url": "https://cab"}


def test_upgrade_without_panel_or_bots_creates_one_hour_setting(monkeypatch):
    migration = _module()
    engine = _engine()
    with engine.begin() as conn:
        monkeypatch.setattr(migration, "op", _Op(conn))
        migration.upgrade()
        panel = json.loads(conn.execute(text("SELECT data FROM global_settings WHERE \"key\" = 'panel'")).scalar())
        assert panel == {"sub_update_interval": "1"}


def test_downgrade_restores_panel_value_to_every_bot_and_removes_it_from_panel(monkeypatch):
    migration = _module()
    engine = _engine()
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO bot_settings (bot_id, data) VALUES (1, :data)"),
            {"data": json.dumps({"show_ads": False})},
        )
        conn.execute(
            text(
                'INSERT INTO global_settings ("key", data, created_at, updated_at) '
                "VALUES ('panel', :data, '2026-01-01', '2026-01-01')"
            ),
            {"data": json.dumps({"sub_update_interval": "7", "bs_monthly_limit": 10})},
        )
        monkeypatch.setattr(migration, "op", _Op(conn))
        migration.downgrade()

        bot = json.loads(conn.execute(text("SELECT data FROM bot_settings WHERE bot_id = 1")).scalar())
        panel = json.loads(conn.execute(text("SELECT data FROM global_settings WHERE \"key\" = 'panel'")).scalar())
        assert bot == {"show_ads": False, "sub_update_interval": "7"}
        assert panel == {"bs_monthly_limit": 10}
