"""store source-qualified tunnel pins

Revision ID: 8f67d00d6215
Revises: b4f7e12a9c68
Create Date: 2026-11-25 16:24:51.497815

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "8f67d00d6215"
down_revision = "b4f7e12a9c68"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_node_pins", sa.Column("tunnel_targets", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("user_node_pins", "tunnel_targets")
