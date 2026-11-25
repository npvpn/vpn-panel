"""version location membership per bot

Revision ID: 2c261b8580d6
Revises: 8f67d00d6215
Create Date: 2026-11-25 16:37:52.627977

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

# revision identifiers, used by Alembic.
revision = "2c261b8580d6"
down_revision = "8f67d00d6215"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("location_refresh_lock", sa.Column("id", sa.Integer, primary_key=True))
    op.execute("INSERT INTO location_refresh_lock (id) VALUES (1)")
    op.create_table(
        "location_memberships",
        sa.Column("id", sa.Integer, primary_key=True),
        *[sa.Column(name, sa.Integer, nullable=False) for name in ("bot_id", "host_id", "source_host_id")],
        sa.Column("node_id", sa.Integer),
        *[
            sa.Column(name, sa.Text, nullable=False)
            for name in ("address", "remark", "source_name", "inbound", "source_inbound")
        ],
        sa.Column("composite", sa.Boolean, nullable=False),
        sa.Column("valid_from", sa.DateTime().with_variant(DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("valid_until", sa.DateTime().with_variant(DATETIME(fsp=6), "mysql")),
    )
    op.create_index(
        "ix_location_audience_node", "location_memberships", ["bot_id", "node_id", "valid_until", "valid_from"]
    )
    op.create_index("ix_location_active", "location_memberships", ["valid_until"])
    op.execute("""CREATE VIEW location_node_history AS SELECT bot_id, host_id, source_host_id,
               node_id, remark, valid_from, valid_until FROM location_memberships WHERE node_id IS NOT NULL""")
    op.execute("""CREATE VIEW location_current_nodes AS SELECT DISTINCT bot_id, host_id, node_id, remark
               FROM location_node_history WHERE valid_until IS NULL""")


def downgrade() -> None:
    op.execute("DROP VIEW location_current_nodes")
    op.execute("DROP VIEW location_node_history")
    op.drop_table("location_memberships")
    op.drop_table("location_refresh_lock")
