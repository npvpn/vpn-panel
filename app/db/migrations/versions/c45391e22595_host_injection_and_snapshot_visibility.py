"""host injection and snapshot visibility

Revision ID: c45391e22595
Revises: e52ac058ffa1
Create Date: 2026-10-23 15:51:50.061140

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c45391e22595"
down_revision = "e52ac058ffa1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("hosts", sa.Column("host_injection", sa.JSON(), nullable=True))
    op.add_column("hosts", sa.Column("group_tag", sa.String(128), nullable=False, server_default=""))
    op.add_column("hosts", sa.Column("is_hidden", sa.Boolean(), nullable=False, server_default="0"))
    op.add_column(
        "host_composition_snapshots", sa.Column("is_composite", sa.Boolean(), nullable=False, server_default="0")
    )
    op.add_column(
        "host_composition_snapshots", sa.Column("is_hidden", sa.Boolean(), nullable=False, server_default="0")
    )


def downgrade() -> None:
    op.drop_column("host_composition_snapshots", "is_hidden")
    op.drop_column("host_composition_snapshots", "is_composite")
    op.drop_column("hosts", "is_hidden")
    op.drop_column("hosts", "group_tag")
    op.drop_column("hosts", "host_injection")
