"""npvpn_2044_bot_bs_daily

Суточный агрегат БС-трафика по ботам — источник колонки «БС-трафик» в счёте
партнёру. FK на bots/nodes здесь нет намеренно: это архивная запись, и удаление
ноды или бота не должно стирать трафик, за который уже выставлен счёт
(см. докстринг модели BotBsDaily).

Revision ID: 177e3212d713
Revises: 0a84f32baf25
Create Date: 2026-10-02 10:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "177e3212d713"
down_revision = "0a84f32baf25"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bot_bs_daily",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bot_id", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("used_bytes", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bot_id", "node_id", "day", name="uq_bot_bs_daily"),
    )
    op.create_index("ix_bot_bs_daily_bot_id", "bot_bs_daily", ["bot_id"])
    op.create_index("ix_bot_bs_daily_node_id", "bot_bs_daily", ["node_id"])
    op.create_index("ix_bot_bs_daily_day", "bot_bs_daily", ["day"])


def downgrade() -> None:
    op.drop_table("bot_bs_daily")
