"""Реальные операции Alembic над прежней схемой, включая откат и CASCADE."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_upgrade_downgrade_preserves_legacy_host_and_cascades(monkeypatch):
    path = (
        Path(__file__).parents[1] / "app/db/migrations/versions/e52ac058ffa1_host_balancing_settings_and_entry_nodes.py"
    )
    spec = importlib.util.spec_from_file_location("host_balancing_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        conn.exec_driver_sql("CREATE TABLE hosts (id INTEGER PRIMARY KEY, address VARCHAR(255))")
        conn.exec_driver_sql("CREATE TABLE nodes (id INTEGER PRIMARY KEY)")
        conn.exec_driver_sql("INSERT INTO hosts VALUES (1, 'legacy.example')")
        conn.exec_driver_sql("INSERT INTO nodes VALUES (1), (2)")
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(conn)))
        migration.upgrade()
        assert conn.exec_driver_sql("SELECT address, balancing, balancer_nodes_source FROM hosts").one() == (
            "legacy.example",
            None,
            "host",
        )
        conn.exec_driver_sql("INSERT INTO host_balancer_nodes VALUES (1, 1), (1, 2)")
        conn.exec_driver_sql("DELETE FROM nodes WHERE id=1")
        assert conn.exec_driver_sql("SELECT node_id FROM host_balancer_nodes").scalars().all() == [2]
        conn.exec_driver_sql("INSERT INTO hosts (id) VALUES (2)")
        conn.exec_driver_sql("INSERT INTO host_balancer_nodes VALUES (2, 2)")
        conn.exec_driver_sql("DELETE FROM hosts WHERE id=2")
        assert conn.exec_driver_sql("SELECT host_id FROM host_balancer_nodes").scalars().all() == [1]
        migration.downgrade()
        assert "host_balancer_nodes" not in sa.inspect(conn).get_table_names()
        assert [c["name"] for c in sa.inspect(conn).get_columns("hosts")] == ["id", "address"]
        assert conn.exec_driver_sql("SELECT address FROM hosts").scalar_one() == "legacy.example"
