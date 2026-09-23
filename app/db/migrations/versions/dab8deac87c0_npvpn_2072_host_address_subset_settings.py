"""NPVPN-2072 host address subset settings

Revision ID: dab8deac87c0
Revises: f9cc88485133
Create Date: 2026-09-21 13:43:55.417180

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'dab8deac87c0'
down_revision = 'f9cc88485133'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Настройки сужения адресов переезжают с бота на хост (NPVPN-2072).

    Бэкфилл не нужен: пер-ботовая фича нигде не была включена (дефолт enabled=False),
    переносить нечего — все хосты стартуют выключенными.
    """
    op.add_column(
        "hosts",
        sa.Column("address_subset_enabled", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.add_column("hosts", sa.Column("address_subset_size", sa.Integer(), nullable=True))
    op.add_column("hosts", sa.Column("address_rotation_days", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("hosts", "address_rotation_days")
    op.drop_column("hosts", "address_subset_size")
    op.drop_column("hosts", "address_subset_enabled")
