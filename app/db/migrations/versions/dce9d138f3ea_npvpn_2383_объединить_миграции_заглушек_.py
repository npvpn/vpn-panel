"""NPVPN-2383: объединить миграции заглушек и сессий нод

Revision ID: dce9d138f3ea
Revises: 8d7f23830001, c4e91a27b803
Create Date: 2026-11-17 19:22:29.713910

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'dce9d138f3ea'
down_revision = ('8d7f23830001', 'c4e91a27b803')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
