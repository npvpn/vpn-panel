"""слияние last_ip и текстов подписки

Revision ID: b47f383fbc9b
Revises: c77c9061b8d4, c8a1b23e4f5
Create Date: 2026-10-21 09:34:03.774628

Две ветки влиты в master параллельно: c77c9061b8d4 (last_ip у user_devices)
и c8a1b23e4f5 (тексты подписки перенесены в настройки панели).
Ветки независимы, порядок применения не важен. Без этого слияния
`alembic upgrade head` падает с Multiple head revisions.
"""

revision = "b47f383fbc9b"
down_revision = ("c77c9061b8d4", "c8a1b23e4f5")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
