"""npvpn_2044_host_rental_marks

Отметка аренды на привязке хоста к боту: когда и как бот получил этот хост.

Backfill не нужен: `server_default` даёт существующим строкам `manual`, и это
правда — все нынешние привязки сделаны руками. Объявить их `self_service`
значило бы начислить партнёрам аренду за хосты, которые мы отдали сами.

Revision ID: 0a84f32baf25
Revises: d155a50b86b0
Create Date: 2026-10-01 21:30:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0a84f32baf25"
down_revision = "d155a50b86b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("host_bot_association", sa.Column("rented_at", sa.DateTime(), nullable=True))
    op.add_column(
        "host_bot_association",
        sa.Column("source", sa.String(length=16), nullable=False, server_default=sa.text("'manual'")),
    )


def downgrade() -> None:
    op.drop_column("host_bot_association", "source")
    op.drop_column("host_bot_association", "rented_at")
