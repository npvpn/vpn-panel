"""npvpn 2383 information host placeholder

Revision ID: 8d7f23830001
Revises: f3c8a91e2b47
Create Date: 2026-11-13 15:06:20.721258

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "8d7f23830001"
down_revision = "f3c8a91e2b47"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "hosts",
        sa.Column("is_placeholder", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )


def downgrade() -> None:
    op.drop_column("hosts", "is_placeholder")
