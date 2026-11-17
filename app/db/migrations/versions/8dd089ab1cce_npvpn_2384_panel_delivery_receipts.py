"""npvpn 2384 panel delivery receipts

Revision ID: 8dd089ab1cce
Revises: f3c8a91e2b47
Create Date: 2026-11-16 19:42:02.968988

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8dd089ab1cce'
down_revision = 'f3c8a91e2b47'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "panel_delivery_receipts",
        sa.Column("operation_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("delta_bytes", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("operation_id"),
    )
    op.create_index(op.f("ix_panel_delivery_receipts_user_id"), "panel_delivery_receipts", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_panel_delivery_receipts_user_id"), table_name="panel_delivery_receipts")
    op.drop_table("panel_delivery_receipts")
