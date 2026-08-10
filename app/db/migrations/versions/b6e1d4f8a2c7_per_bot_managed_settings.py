"""per bot managed settings

Revision ID: b6e1d4f8a2c7
Revises: 9b1d29ea4018
Create Date: 2026-08-10 16:05:00.000000

"""
import sqlalchemy as sa
from alembic import op


revision = "b6e1d4f8a2c7"
down_revision = "9b1d29ea4018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing bots must opt in. After the columns are installed, the database
    # default is switched to true so bots created by newer code start enabled.
    with op.batch_alter_table("bots") as batch_op:
        batch_op.add_column(sa.Column("source_bot_id", sa.BigInteger(), nullable=True))
        batch_op.add_column(
            sa.Column("admin_sync_enabled", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.create_index("ix_bots_source_bot_id", ["source_bot_id"], unique=True)

    with op.batch_alter_table("bots") as batch_op:
        batch_op.alter_column(
            "admin_sync_enabled",
            existing_type=sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        )


def downgrade() -> None:
    with op.batch_alter_table("bots") as batch_op:
        batch_op.drop_index("ix_bots_source_bot_id")
        batch_op.drop_column("admin_sync_enabled")
        batch_op.drop_column("source_bot_id")
