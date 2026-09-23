from __future__ import annotations

import glob
import importlib.util
import json
import os

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool


def _load_migration():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    matches = glob.glob(os.path.join(here, "app/db/migrations/versions/*_backfill_v2ray_templates.py"))
    assert len(matches) == 1, f"expected exactly one v2ray backfill migration, got {matches}"
    spec = importlib.util.spec_from_file_location("v2ray_templates_backfill_migration", matches[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE xray_templates ("
                "id INTEGER PRIMARY KEY, slug VARCHAR(64), title VARCHAR(128), "
                "created_at DATETIME, updated_at DATETIME)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE xray_template_versions ("
                "id INTEGER PRIMARY KEY, template_id INTEGER, version INTEGER, body TEXT, "
                "comment VARCHAR(255), author_admin_id INTEGER, author_username VARCHAR(34), "
                "created_at DATETIME, UNIQUE(template_id, version))"
            )
        )
    return engine


def _add_document(conn, template_id: int, slug: str, versions: list[tuple[int, str, str, str]]) -> None:
    conn.execute(
        text("INSERT INTO xray_templates (id, slug, title) VALUES (:id, :slug, :title)"),
        {"id": template_id, "slug": slug, "title": slug},
    )
    for version, body, comment, author in versions:
        conn.execute(
            text(
                "INSERT INTO xray_template_versions "
                "(template_id, version, body, comment, author_username) "
                "VALUES (:template_id, :version, :body, :comment, :author)"
            ),
            {
                "template_id": template_id,
                "version": version,
                "body": body,
                "comment": comment,
                "author": author,
            },
        )


def _versions(conn, slug: str) -> list[tuple[int, str, str]]:
    return conn.execute(
        text(
            "SELECT v.version, v.body, v.comment "
            "FROM xray_template_versions v "
            "JOIN xray_templates t ON t.id = v.template_id "
            "WHERE t.slug = :slug ORDER BY v.version"
        ),
        {"slug": slug},
    ).all()


def test_empty_migrated_documents_receive_the_file_template(monkeypatch):
    migration = _load_migration()
    file_body = '{\n  "dns": {"servers": ["9.9.9.9"]},\n  "outbounds": []\n}'
    monkeypatch.setattr(migration, "_file_template_body", lambda: file_body)
    engine = _engine()

    with engine.begin() as conn:
        for template_id, slug in ((1, "default"), (2, "bs")):
            _add_document(
                conn,
                template_id,
                slug,
                [(1, "", migration.SOURCE_COMMENT, migration.SOURCE_AUTHOR)],
            )
        migration._backfill(conn)

        for slug in migration.TARGET_SLUGS:
            versions = _versions(conn, slug)
            assert versions == [
                (1, "", migration.SOURCE_COMMENT),
                (2, file_body, migration.BACKFILL_COMMENT),
            ]


def test_admin_changes_and_nonempty_migration_values_are_not_overwritten(monkeypatch):
    migration = _load_migration()
    monkeypatch.setattr(migration, "_file_template_body", lambda: '{"from": "file"}')
    engine = _engine()

    with engine.begin() as conn:
        _add_document(
            conn,
            1,
            "default",
            [(1, '{"from": "settings"}', migration.SOURCE_COMMENT, migration.SOURCE_AUTHOR)],
        )
        _add_document(
            conn,
            2,
            "bs",
            [
                (1, "", migration.SOURCE_COMMENT, migration.SOURCE_AUTHOR),
                (2, "", "очищено администратором", "admin"),
            ],
        )
        migration._backfill(conn)

        assert len(_versions(conn, "default")) == 1
        assert len(_versions(conn, "bs")) == 2


def test_invalid_or_unavailable_file_does_not_break_upgrade(monkeypatch):
    migration = _load_migration()
    engine = _engine()
    with engine.begin() as conn:
        _add_document(conn, 1, "default", [(1, "", migration.SOURCE_COMMENT, migration.SOURCE_AUTHOR)])

        monkeypatch.setattr(migration, "_file_template_body", lambda: "[1, 2]")
        migration._backfill(conn)
        assert len(_versions(conn, "default")) == 1

        monkeypatch.setattr(
            migration,
            "_file_template_body",
            lambda: (_ for _ in ()).throw(RuntimeError("template is unavailable")),
        )
        migration._backfill(conn)
        assert len(_versions(conn, "default")) == 1


def test_downgrade_removes_only_versions_created_by_backfill(monkeypatch):
    migration = _load_migration()
    monkeypatch.setattr(migration, "_file_template_body", lambda: json.dumps({"outbounds": []}))
    engine = _engine()

    with engine.begin() as conn:
        _add_document(conn, 1, "default", [(1, "", migration.SOURCE_COMMENT, migration.SOURCE_AUTHOR)])
        migration._backfill(conn)
        _add_document(
            conn,
            2,
            "custom",
            [(2, '{"custom": true}', "другая версия", migration.SOURCE_AUTHOR)],
        )

        migration._rollback(conn)

        assert _versions(conn, "default") == [(1, "", migration.SOURCE_COMMENT)]
        assert _versions(conn, "custom") == [(2, '{"custom": true}', "другая версия")]
