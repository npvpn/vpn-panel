"""Remember REST node control sessions across panel restarts.

Revision ID: c4e91a27b803
Revises: f3c8a91e2b47
Create Date: 2026-11-13 18:28:53.776280

"""
import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "c4e91a27b803"
down_revision = "f3c8a91e2b47"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("nodes") as batch_op:
        batch_op.add_column(sa.Column("control_session_id", sa.String(length=36), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("nodes") as batch_op:
        batch_op.drop_column("control_session_id")
