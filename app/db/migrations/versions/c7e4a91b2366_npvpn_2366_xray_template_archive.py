"""NPVPN-2366 archive client xray configs

Revision ID: c7e4a91b2366
Revises: d35990c1e6fe
Create Date: 2026-11-24 17:51:12.624035

"""

import sqlalchemy as sa
from alembic import op

revision = "c7e4a91b2366"
down_revision = "d35990c1e6fe"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("xray_templates") as batch_op:
        batch_op.add_column(sa.Column("archived_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("archived_by", sa.String(length=34), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("xray_templates") as batch_op:
        batch_op.drop_column("archived_by")
        batch_op.drop_column("archived_at")
