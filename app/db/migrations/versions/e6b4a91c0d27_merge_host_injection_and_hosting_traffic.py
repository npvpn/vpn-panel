"""слияние голов инжекта хостов и поправок трафика хостинга

Revision ID: e6b4a91c0d27
Revises: 70907486dd1d, c45391e22595
Create Date: 2026-10-27 22:05:02.505411

Две ветки влиты параллельно: c45391e22595 (композиция хостов, таблица hosts
и снимки) и 70907486dd1d (журнал поправок трафика хостинга). Ветки
независимы, порядок применения не важен. Без этого слияния
`alembic upgrade head` на старте контейнера падает с Multiple head revisions.
"""

revision = "e6b4a91c0d27"
down_revision = ("70907486dd1d", "c45391e22595")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
