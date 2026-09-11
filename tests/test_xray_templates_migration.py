from __future__ import annotations

import glob
import importlib.util
import json
import os

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool


def _load_migration():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    matches = glob.glob(os.path.join(here, "app/db/migrations/versions/*_xray_template_versions.py"))
    assert len(matches) == 1, f"expected exactly one xray templates migration, got {matches}"
    spec = importlib.util.spec_from_file_location("xray_templates_migration", matches[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Op:
    def __init__(self, bind):
        self._bind = bind

    def get_bind(self):
        return self._bind


def _engine(panel_data: dict, nodes: list[tuple[int, int]]):
    """Песочница: global_settings + nodes + пустые целевые таблицы."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE global_settings ("
                '"key" VARCHAR(64) PRIMARY KEY, data TEXT, created_at DATETIME, updated_at DATETIME)'
            )
        )
        conn.execute(text("CREATE TABLE nodes (id INTEGER PRIMARY KEY, is_bs BOOLEAN, routing_profile_id INTEGER)"))
        conn.execute(
            text(
                "CREATE TABLE xray_templates (id INTEGER PRIMARY KEY, kind VARCHAR(32), slug VARCHAR(64), "
                "title VARCHAR(128), created_at DATETIME, updated_at DATETIME)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE xray_template_versions (id INTEGER PRIMARY KEY, template_id INTEGER, "
                "version INTEGER, body TEXT, comment VARCHAR(255), author_admin_id INTEGER, "
                "author_username VARCHAR(34), created_at DATETIME)"
            )
        )
        conn.execute(
            text('INSERT INTO global_settings ("key", data) VALUES (:k, :d)'),
            {"k": "panel", "d": json.dumps(panel_data)},
        )
        for node_id, is_bs in nodes:
            conn.execute(
                text("INSERT INTO nodes (id, is_bs, routing_profile_id) VALUES (:i, :b, NULL)"),
                {"i": node_id, "b": is_bs},
            )
    return engine


def test_migration_follows_master_head():
    assert _load_migration().down_revision == "03e94a203122"


def test_flat_keys_become_first_versions():
    migration = _load_migration()
    engine = _engine(
        {
            "sub_custom_headers": "X-A: 1",
            "sub_v2ray_json_template": '{"outbounds": []}',
            "sub_routing_json_default": '{"rules": []}',
            "sub_routing_json_bs": "",
        },
        nodes=[(1, 1), (2, 0)],
    )
    with engine.begin() as conn:
        migration._migrate_data(_Op(conn))
        rows = conn.execute(
            text(
                "SELECT t.slug, t.kind, v.version, v.body, v.author_username "
                "FROM xray_templates t JOIN xray_template_versions v ON v.template_id = t.id"
            )
        ).all()
    by_slug = {slug: (kind, version, body, author) for slug, kind, version, body, author in rows}
    assert by_slug["v2ray_json"] == ("template", 1, '{"outbounds": []}', "migration")
    assert by_slug["default"] == ("routing_profile", 1, '{"rules": []}', "migration")
    # Пустое значение тоже получает версию 1 — у каждого документа есть лента.
    assert by_slug["bs"] == ("routing_profile", 1, "", "migration")


def test_bs_nodes_get_bs_profile_and_others_stay_null():
    migration = _load_migration()
    engine = _engine(
        {"sub_v2ray_json_template": "", "sub_routing_json_default": "", "sub_routing_json_bs": ""},
        nodes=[(1, 1), (2, 0)],
    )
    with engine.begin() as conn:
        migration._migrate_data(_Op(conn))
        bs_id = conn.execute(text("SELECT id FROM xray_templates WHERE slug = 'bs'")).scalar_one()
        mapping = dict(conn.execute(text("SELECT id, routing_profile_id FROM nodes")).all())
    assert mapping == {1: bs_id, 2: None}


def test_flat_keys_are_stripped_from_panel_settings():
    migration = _load_migration()
    engine = _engine(
        {
            "sub_custom_headers": "X-A: 1",
            "sub_v2ray_json_template": '{"a": 1}',
            "sub_routing_json_default": "",
            "sub_routing_json_bs": "",
        },
        nodes=[],
    )
    with engine.begin() as conn:
        migration._migrate_data(_Op(conn))
        raw = conn.execute(text('SELECT data FROM global_settings WHERE "key" = :k'), {"k": "panel"}).scalar_one()
    data = json.loads(raw)
    assert data == {"sub_custom_headers": "X-A: 1"}


def test_downgrade_restores_flat_keys():
    migration = _load_migration()
    engine = _engine(
        {
            "sub_v2ray_json_template": '{"outbounds": []}',
            "sub_routing_json_default": '{"rules": []}',
            "sub_routing_json_bs": "",
        },
        nodes=[(1, 1)],
    )
    with engine.begin() as conn:
        migration._migrate_data(_Op(conn))
        migration._rollback_data(_Op(conn))
        raw = conn.execute(text('SELECT data FROM global_settings WHERE "key" = :k'), {"k": "panel"}).scalar_one()
    data = json.loads(raw)
    assert data["sub_v2ray_json_template"] == '{"outbounds": []}'
    assert data["sub_routing_json_default"] == '{"rules": []}'
    assert data["sub_routing_json_bs"] == ""
