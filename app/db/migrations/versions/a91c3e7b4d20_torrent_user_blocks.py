"""torrent user blocks

Revision ID: a91c3e7b4d20
Revises: b4f7e12a9c68
Create Date: 2026-11-27 11:20:15.471259

"""

import sqlalchemy as sa
from alembic import op

revision = "a91c3e7b4d20"
down_revision = "b4f7e12a9c68"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "torrent_user_blocks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("node_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("blocked_until", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("node_id", "user_id", name="uq_torrent_user_blocks"),
    )
    op.create_index("ix_torrent_user_blocks_node_id", "torrent_user_blocks", ["node_id"])
    op.create_index("ix_torrent_user_blocks_user_id", "torrent_user_blocks", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_torrent_user_blocks_user_id", table_name="torrent_user_blocks")
    op.drop_index("ix_torrent_user_blocks_node_id", table_name="torrent_user_blocks")
    op.drop_table("torrent_user_blocks")
