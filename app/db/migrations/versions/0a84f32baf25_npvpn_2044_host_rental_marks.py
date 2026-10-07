"""npvpn_2044_host_rental_marks

Отметка аренды на привязке хоста к боту: с какого момента бот её арендует.

Аренда — это непустой `rented_at`; служебные привязки (поставили на время
разбирательства) остаются с NULL и в счёт не идут. Backfill не нужен: нынешние
привязки сделаны руками и за них никто не платит, поэтому NULL — это правда.

Колонки `source` здесь нет намеренно: самообслуживания в задаче нет, значение
всегда было бы 'manual', и на прод уехала бы колонка-мусор.

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


def downgrade() -> None:
    op.drop_column("host_bot_association", "rented_at")
