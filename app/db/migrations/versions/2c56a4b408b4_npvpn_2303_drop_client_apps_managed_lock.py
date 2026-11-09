"""npvpn_2303 drop client apps managed lock

Revision ID: 2c56a4b408b4
Revises: b7e4c2a93111
Create Date: 2026-11-09 11:34:24.978015

"""

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "2c56a4b408b4"
down_revision = "b7e4c2a93111"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("DELETE FROM managed_settings WHERE `key` = 'client_apps'"))


def downgrade() -> None:
    pass
