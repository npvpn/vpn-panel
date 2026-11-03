"""npvpn_2311 host finalmask

Revision ID: b7e4c2a93111
Revises: e6b4a91c0d27
Create Date: 2026-11-03 13:52:02.572362

"""

import sqlalchemy as sa
from alembic import op

revision = "b7e4c2a93111"
down_revision = "e6b4a91c0d27"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("hosts", sa.Column("finalmask", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("hosts", "finalmask")
