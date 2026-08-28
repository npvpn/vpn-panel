from __future__ import annotations

import glob
import importlib.util
import json
import os

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool


def _load_migration():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    matches = glob.glob(os.path.join(here, "app/db/migrations/versions/*_legacy_jwt_keys_to_panel_settings.py"))
    assert len(matches) == 1, f"expected exactly one legacy jwt keys migration, got {matches}"
    spec = importlib.util.spec_from_file_location("legacy_jwt_keys_migration", matches[0])
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
        conn.execute(
            text(
                "CREATE TABLE global_settings ("
                '"key" VARCHAR(64) PRIMARY KEY, data TEXT, created_at DATETIME, updated_at DATETIME)'
            )
        )
    return engine


def test_upgrade_inserts_panel_row_from_env(monkeypatch):
    migration = _load_migration()
    monkeypatch.setenv("SUBSCRIPTION_LEGACY_SECRET_KEYS", "aaa,bbb, aaa")
    engine = _engine()
    with engine.begin() as conn:
        monkeypatch.setattr(migration, "op", _Op(conn))
        migration.upgrade()
        panel = json.loads(
            conn.execute(text('SELECT data FROM global_settings WHERE "key" = :k'), {"k": "panel"}).scalar()
        )
    assert panel["subscription_legacy_secret_keys"] == ["aaa", "bbb"]


def test_upgrade_fills_empty_existing_row(monkeypatch):
    migration = _load_migration()
    monkeypatch.setenv("SUBSCRIPTION_LEGACY_SECRET_KEYS", "from-env")
    engine = _engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                'INSERT INTO global_settings ("key", data, created_at, updated_at) '
                "VALUES ('panel', :data, '2026-01-01', '2026-01-01')"
            ),
            {"data": json.dumps({"bs_monthly_limit": 1, "sub_custom_headers": "X-A: 1"})},
        )
        monkeypatch.setattr(migration, "op", _Op(conn))
        migration.upgrade()
        panel = json.loads(
            conn.execute(text('SELECT data FROM global_settings WHERE "key" = :k'), {"k": "panel"}).scalar()
        )
    assert panel["subscription_legacy_secret_keys"] == ["from-env"]
    assert panel["bs_monthly_limit"] == 1
    assert panel["sub_custom_headers"] == "X-A: 1"


def test_upgrade_does_not_overwrite_existing_keys(monkeypatch):
    migration = _load_migration()
    monkeypatch.setenv("SUBSCRIPTION_LEGACY_SECRET_KEYS", "env-key")
    engine = _engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                'INSERT INTO global_settings ("key", data, created_at, updated_at) '
                "VALUES ('panel', :data, '2026-01-01', '2026-01-01')"
            ),
            {"data": json.dumps({"subscription_legacy_secret_keys": ["already"]})},
        )
        monkeypatch.setattr(migration, "op", _Op(conn))
        migration.upgrade()
        panel = json.loads(
            conn.execute(text('SELECT data FROM global_settings WHERE "key" = :k'), {"k": "panel"}).scalar()
        )
    assert panel["subscription_legacy_secret_keys"] == ["already"]


def test_downgrade_removes_field(monkeypatch):
    migration = _load_migration()
    engine = _engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                'INSERT INTO global_settings ("key", data, created_at, updated_at) '
                "VALUES ('panel', :data, '2026-01-01', '2026-01-01')"
            ),
            {"data": json.dumps({"bs_monthly_limit": 3, "subscription_legacy_secret_keys": ["x"]})},
        )
        monkeypatch.setattr(migration, "op", _Op(conn))
        migration.downgrade()
        panel = json.loads(
            conn.execute(text('SELECT data FROM global_settings WHERE "key" = :k'), {"k": "panel"}).scalar()
        )
    assert "subscription_legacy_secret_keys" not in panel
    assert panel["bs_monthly_limit"] == 3
