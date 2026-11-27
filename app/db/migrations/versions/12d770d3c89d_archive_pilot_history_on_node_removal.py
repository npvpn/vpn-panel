"""archive pilot history on node removal

Revision ID: 12d770d3c89d
Revises: 3015148dc428
Create Date: 2026-11-27 13:59:23.575307

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '12d770d3c89d'
down_revision = '3015148dc428'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("haproxy_pilot_operations", sa.Column("archived_at", sa.DateTime(), nullable=True))
    op.execute(
        "UPDATE haproxy_pilot_operations SET archived_at = CURRENT_TIMESTAMP, pending_node_id = NULL "
        "WHERE NOT EXISTS (SELECT 1 FROM nodes WHERE nodes.id = haproxy_pilot_operations.node_id)"
    )


def downgrade() -> None:
    op.drop_column("haproxy_pilot_operations", "archived_at")
