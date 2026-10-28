"""node hosting traffic adjustments

Revision ID: 70907486dd1d
Revises: b47f383fbc9b
Create Date: 2026-10-26 12:26:10.028570

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "70907486dd1d"
down_revision = "b47f383fbc9b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "node_hosting_traffic_adjustments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("node_id", sa.Integer(), sa.ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("raw_bytes", sa.BigInteger(), nullable=False),
        sa.Column("actual_bytes", sa.BigInteger(), nullable=False),
        sa.Column("delta_bytes", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.Column("cancel_reason", sa.String(500), nullable=True),
    )
    op.create_index("ix_node_hosting_traffic_adjustments_node_id", "node_hosting_traffic_adjustments", ["node_id"])
    op.create_index(
        "ix_node_hosting_traffic_adjustments_created_at", "node_hosting_traffic_adjustments", ["created_at"]
    )


def downgrade() -> None:
    op.drop_table("node_hosting_traffic_adjustments")
