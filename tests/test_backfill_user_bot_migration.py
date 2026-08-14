"""NPVPN-1842: бэкфилл привязки юзеров к боту на single-bot панели."""

import glob
import importlib.util
import os

import sqlalchemy as sa


def _load_migration():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    matches = glob.glob(os.path.join(here, "app/db/migrations/versions/*_npvpn_1842_backfill_user_bot.py"))
    assert len(matches) == 1, f"expected exactly one backfill migration, got {matches}"
    spec = importlib.util.spec_from_file_location("backfill_user_bot_migration", matches[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _prepare(conn, bots: list[int]) -> None:
    conn.execute(sa.text("CREATE TABLE bots (id INTEGER PRIMARY KEY, username TEXT)"))
    conn.execute(sa.text("CREATE TABLE users (id INTEGER PRIMARY KEY, bot_id INTEGER)"))
    for bot_id in bots:
        conn.execute(sa.text("INSERT INTO bots (id, username) VALUES (:id, :u)"), {"id": bot_id, "u": f"bot{bot_id}"})
    conn.execute(sa.text("INSERT INTO users (id, bot_id) VALUES (1, NULL), (2, NULL), (3, 7)"))


def _bot_ids(conn) -> list:
    return [row[1] for row in conn.execute(sa.text("SELECT id, bot_id FROM users ORDER BY id")).fetchall()]


def test_single_bot_gets_backfilled():
    module = _load_migration()
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        _prepare(conn, bots=[5])

        module._backfill(conn)

        assert _bot_ids(conn) == [5, 5, 7]


def test_multi_bot_panel_is_untouched():
    module = _load_migration()
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        _prepare(conn, bots=[5, 6])

        module._backfill(conn)

        assert _bot_ids(conn) == [None, None, 7]


def test_panel_without_bots_is_untouched():
    module = _load_migration()
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        _prepare(conn, bots=[])

        module._backfill(conn)

        assert _bot_ids(conn) == [None, None, 7]


def test_migration_downgrade_is_noop():
    module = _load_migration()
    assert hasattr(module, "upgrade")
    assert hasattr(module, "downgrade")
    module.downgrade()
