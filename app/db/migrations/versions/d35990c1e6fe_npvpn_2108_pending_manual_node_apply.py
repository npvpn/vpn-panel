"""NPVPN-2108 pending manual node apply

Revision ID: d35990c1e6fe
Revises: d5c3b20d0d3a
Create Date: 2026-11-18 12:34:07.367734

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d35990c1e6fe"
down_revision = "d5c3b20d0d3a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("nodes") as batch_op:
        batch_op.add_column(sa.Column("config_apply_pending", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("nodes") as batch_op:
        batch_op.drop_column("config_apply_pending")
