"""add haproxy pilot operation history

Revision ID: 3015148dc428
Revises: 2c261b8580d6
Create Date: 2026-11-27 13:42:51.681938

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


# revision identifiers, used by Alembic.
revision = '3015148dc428'
down_revision = '2c261b8580d6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "haproxy_pilot_operations",
        sa.Column("operation_id", sa.String(36), primary_key=True),
        sa.Column("node_id", sa.Integer(), nullable=False),
        sa.Column("pending_node_id", sa.Integer(), unique=True),
        sa.Column("endpoint", sa.JSON(), nullable=False),
        sa.Column("operator", sa.String(256), nullable=False),
        sa.Column("created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("expected_revision", sa.Integer(), nullable=False),
        sa.Column("target", sa.String(256), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("target_address", sa.String(256), nullable=False),
        sa.Column("target_port", sa.Integer(), nullable=False),
        sa.Column("exit_node_id", sa.Integer(), nullable=False),
        sa.Column("inbound_tag", sa.String(256), nullable=False),
        sa.Column("outcome", sa.String(24), nullable=False),
        sa.Column("revision", sa.Integer()),
        sa.Column("detail", sa.Text(), nullable=False),
    )
    op.create_index("ix_pilot_node_time", "haproxy_pilot_operations", ["node_id", "created_at", "operation_id"])


def downgrade() -> None:
    op.drop_table("haproxy_pilot_operations")
