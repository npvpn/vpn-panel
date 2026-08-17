from __future__ import annotations

import glob
import importlib.util
import json
import os

import sqlalchemy as sa
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

GB = 1024**3


def _load_migration():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    matches = glob.glob(os.path.join(here, "app/db/migrations/versions/*_move_panel_settings.py"))
    assert len(matches) == 1, f"expected exactly one panel settings migration, got {matches}"
    spec = importlib.util.spec_from_file_location("panel_settings_migration", matches[0])
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


def test_parse_json_accepts_dict_str_bytes():
    migration = _load_migration()
    assert migration._parse_json({"a": 1}) == {"a": 1}
    assert migration._parse_json('{"a": 1}') == {"a": 1}
    assert migration._parse_json(b'{"a": 1}') == {"a": 1}
    assert migration._parse_json(None) == {}


def test_pick_takes_first_nonempty_per_field():
    migration = _load_migration()
    rows = [
        (
            1,
            {
                "sub_custom_headers": "X-A: 1",
                "bs_monthly_limit": 0,
                "sub_routing_happ": "",
                "sub_v2ray_json_template": "",
            },
        ),
        (
            2,
            {
                "sub_custom_headers": "X-B: 2",
                "bs_monthly_limit": 3 * GB,
                "sub_routing_happ": "happ://from-two",
                "sub_v2ray_json_template": '{"dns": {}}',
            },
        ),
    ]
    picked = migration._pick_panel_settings(rows)
    assert picked["sub_custom_headers"] == "X-A: 1"
    assert picked["bs_monthly_limit"] == 3 * GB
    assert picked["sub_routing_happ"] == "happ://from-two"
    assert picked["sub_v2ray_json_template"] == '{"dns": {}}'
    assert picked["sub_routing_v2raytun"] == ""
    assert picked["sub_routing_json_default"] == ""
    assert picked["sub_routing_json_bs"] == ""


def test_strip_removes_only_panel_keys():
    migration = _load_migration()
    cleaned = migration._strip_panel_keys(
        {"show_ads": False, "bs_monthly_limit": 1, "sub_custom_headers": "X-A: 1", "web_url": "https://x"}
    )
    assert cleaned == {"show_ads": False, "web_url": "https://x"}


def test_mysql_sql_quotes_reserved_key_column():
    """Регресс: сырой SELECT key ... падает на MySQL (1064, KEY — reserved)."""
    from sqlalchemy.dialects import mysql

    migration = _load_migration()
    gs = migration._global_settings_table()
    compiled = str(sa.select(gs.c.key).where(gs.c.key == "panel").compile(dialect=mysql.dialect()))
    assert "`key`" in compiled
    assert "SELECT key " not in compiled


def test_upgrade_copies_and_strips(monkeypatch):
    migration = _load_migration()
    engine = _engine()
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO bot_settings (bot_id, data) VALUES (:bot_id, :data)"),
            [
                {
                    "bot_id": 1,
                    "data": json.dumps({"show_ads": False, "sub_custom_headers": "X-A: 1", "bs_monthly_limit": 0}),
                },
                {
                    "bot_id": 2,
                    "data": json.dumps(
                        {"show_ads": True, "sub_custom_headers": "", "bs_monthly_limit": 5 * GB, "web_url": "https://b"}
                    ),
                },
            ],
        )
        monkeypatch.setattr(migration, "op", _Op(conn))
        migration.upgrade()

        panel = json.loads(
            conn.execute(
                text('SELECT data FROM global_settings WHERE "key" = :setting_key'), {"setting_key": "panel"}
            ).scalar()
        )
        assert panel["sub_custom_headers"] == "X-A: 1"
        assert panel["bs_monthly_limit"] == 5 * GB

        bot1 = json.loads(conn.execute(text("SELECT data FROM bot_settings WHERE bot_id = 1")).scalar())
        bot2 = json.loads(conn.execute(text("SELECT data FROM bot_settings WHERE bot_id = 2")).scalar())
        assert "bs_monthly_limit" not in bot1 and "sub_custom_headers" not in bot1
        assert bot1["show_ads"] is False
        assert "bs_monthly_limit" not in bot2
        assert bot2["web_url"] == "https://b"


def test_downgrade_writes_snapshot_back_to_all_bots(monkeypatch):
    migration = _load_migration()
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
            {
                "data": json.dumps(
                    {**migration.DEFAULT_PANEL_SETTINGS, "bs_monthly_limit": 9, "sub_routing_happ": "happ://x"}
                )
            },
        )
        monkeypatch.setattr(migration, "op", _Op(conn))
        migration.downgrade()

        bot = json.loads(conn.execute(text("SELECT data FROM bot_settings WHERE bot_id = 1")).scalar())
        assert bot["show_ads"] is False
        assert bot["bs_monthly_limit"] == 9
        assert bot["sub_routing_happ"] == "happ://x"
        assert conn.execute(text('SELECT "key" FROM global_settings WHERE "key" = \'panel\'')).fetchone() is None
