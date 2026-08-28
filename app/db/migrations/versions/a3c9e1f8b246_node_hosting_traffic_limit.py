"""node hosting traffic limit

Revision ID: a3c9e1f8b246
Revises: c9d4e2f1a8b7
Create Date: 2026-08-28 12:38:31.101532

Лимит трафика у хостера на ноду (байты, SI). NULL — лимита нет: на дашборде
черта, алерт не строится. В форме панели вводится в ТБ (дробь, 1 ТБ = 10^12).
"""
from alembic import op
import sqlalchemy as sa


revision = "a3c9e1f8b246"
down_revision = "c9d4e2f1a8b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "nodes",
        sa.Column("hosting_traffic_limit_bytes", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("nodes", "hosting_traffic_limit_bytes")
