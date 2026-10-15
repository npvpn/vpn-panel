from __future__ import annotations

import glob
import importlib.util
import json
import os

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool


def _load_migration():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    matches = glob.glob(os.path.join(here, "app/db/migrations/versions/*_move_subscription_messages.py"))
    assert len(matches) == 1, f"expected exactly one messages migration, got {matches}"
    spec = importlib.util.spec_from_file_location("subscription_messages_migration", matches[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_messages_migration_follows_current_head():
    module = _load_migration()
    assert module.down_revision == "b1c2d3e4f5a6"


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


def test_first_bot_wins_even_if_later_bots_have_other_texts(monkeypatch):
    migration = _load_migration()
    engine = _engine()
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO bot_settings (bot_id, data) VALUES (:bot_id, :data)"),
            [
                {
                    "bot_id": 2,
                    "data": json.dumps(
                        {
                            "show_ads": True,
                            "sub_client_note": "from-second",
                            "sub_revoked_server_text": ["second"],
                        }
                    ),
                },
                {
                    "bot_id": 1,
                    "data": json.dumps(
                        {
                            "show_ads": False,
                            "sub_client_note": "from-first",
                            "sub_revoked_server_text": ["first-a", "first-b"],
                            "sub_bs_limit_server_text": [],
                        }
                    ),
                },
            ],
        )
        conn.execute(
            text(
                'INSERT INTO global_settings ("key", data, created_at, updated_at) '
                "VALUES ('panel', :data, '2026-01-01', '2026-01-01')"
            ),
            {"data": json.dumps({"sub_custom_headers": "X-Keep: 1", "bs_monthly_limit": 10})},
        )
        monkeypatch.setattr(migration, "op", _Op(conn))
        migration.upgrade()

        panel = json.loads(
            conn.execute(
                text('SELECT data FROM global_settings WHERE "key" = :setting_key'), {"setting_key": "panel"}
            ).scalar()
        )
        assert panel["sub_custom_headers"] == "X-Keep: 1"
        assert panel["bs_monthly_limit"] == 10
        assert panel["sub_client_note"] == "from-first"
        assert panel["sub_revoked_server_text"] == ["first-a", "first-b"]
        assert panel["sub_bs_limit_server_text"] == []

        bot1 = json.loads(conn.execute(text("SELECT data FROM bot_settings WHERE bot_id = 1")).scalar())
        bot2 = json.loads(conn.execute(text("SELECT data FROM bot_settings WHERE bot_id = 2")).scalar())
        assert "sub_client_note" not in bot1
        assert "sub_revoked_server_text" not in bot1
        assert bot1["show_ads"] is False
        assert "sub_client_note" not in bot2
        assert bot2["show_ads"] is True


def test_empty_bots_uses_defaults_and_keeps_panel_row(monkeypatch):
    migration = _load_migration()
    engine = _engine()
    with engine.begin() as conn:
        monkeypatch.setattr(migration, "op", _Op(conn))
        migration.upgrade()
        panel = json.loads(
            conn.execute(
                text('SELECT data FROM global_settings WHERE "key" = :setting_key'), {"setting_key": "panel"}
            ).scalar()
        )
        assert panel["sub_client_note"] == migration.DEFAULT_MESSAGES["sub_client_note"]
        assert panel["sub_revoked_server_text"] == migration.DEFAULT_MESSAGES["sub_revoked_server_text"]
        assert panel["sub_bs_limit_server_text"] == []


def test_downgrade_writes_messages_back_to_all_bots(monkeypatch):
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
                    {
                        "sub_custom_headers": "keep",
                        "sub_client_note": "panel-note",
                        "sub_revoked_server_text": ["gone"],
                    }
                )
            },
        )
        monkeypatch.setattr(migration, "op", _Op(conn))
        migration.downgrade()

        bot = json.loads(conn.execute(text("SELECT data FROM bot_settings WHERE bot_id = 1")).scalar())
        assert bot["show_ads"] is False
        assert bot["sub_client_note"] == "panel-note"
        assert bot["sub_revoked_server_text"] == ["gone"]
        panel = json.loads(
            conn.execute(
                text('SELECT data FROM global_settings WHERE "key" = :setting_key'), {"setting_key": "panel"}
            ).scalar()
        )
        assert panel["sub_custom_headers"] == "keep"
        assert "sub_client_note" not in panel
        assert "sub_revoked_server_text" not in panel
