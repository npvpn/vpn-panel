"""NPVPN-2366: колонки архива добавляются и снимаются, строка конфига остаётся."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def test_archive_columns_upgrade_and_downgrade():
    path = next((Path(__file__).parents[1] / "app/db/migrations/versions").glob("*npvpn_2366_xray_template_archive.py"))
    spec = importlib.util.spec_from_file_location("xray_template_archive_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE xray_templates ("
                "id INTEGER PRIMARY KEY, slug VARCHAR(64), title VARCHAR(128), "
                "created_at DATETIME, updated_at DATETIME)"
            )
        )
        conn.execute(text("INSERT INTO xray_templates (id, slug, title) VALUES (1, 'default', 'Обычные')"))
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
            row = conn.execute(text("SELECT archived_at, archived_by FROM xray_templates")).one()
            assert row == (None, None)
            migration.downgrade()
        assert {col["name"] for col in inspect(conn).get_columns("xray_templates")} == {
            "id",
            "slug",
            "title",
            "created_at",
            "updated_at",
        }
        assert conn.execute(text("SELECT slug FROM xray_templates")).scalar_one() == "default"
    engine.dispose()
