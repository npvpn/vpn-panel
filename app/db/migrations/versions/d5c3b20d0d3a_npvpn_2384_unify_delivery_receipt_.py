"""NPVPN-2384: unify delivery receipt migration

Revision ID: d5c3b20d0d3a
Revises: 8dd089ab1cce, dce9d138f3ea
Create Date: 2026-11-17 19:31:41.177061

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd5c3b20d0d3a'
down_revision = ('8dd089ab1cce', 'dce9d138f3ea')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
