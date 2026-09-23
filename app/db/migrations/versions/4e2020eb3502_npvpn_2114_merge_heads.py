"""слияние разъехавшихся голов миграций

Revision ID: 4e2020eb3502
Revises: dab8deac87c0, e8f1a2b3c4d5
Create Date: 2026-09-22 16:41:46.634979

Две ветки влиты в master параллельно: dab8deac87c0 (подмножество адресов хоста,
таблица hosts) и e8f1a2b3c4d5 (пересчёт лимита трафика в TiB, таблица nodes).
Ветки независимы, порядок применения не важен. Без этого слияния
`alembic upgrade head` на старте контейнера падает с Multiple head revisions.
"""

revision = "4e2020eb3502"
down_revision = ("dab8deac87c0", "e8f1a2b3c4d5")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
