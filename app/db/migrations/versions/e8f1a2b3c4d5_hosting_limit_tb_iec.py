"""hosting traffic limit SI TB → IEC TiB

Revision ID: e8f1a2b3c4d5
Revises: 6f9ee5710f34
Create Date: 2026-09-21 11:12:20.232524

Лимит в форме — «ТБ как у хостера и VPN Nodes» (1 ТБ = 2^40 байт), не SI 10^12.
Уже сохранённые значения пересчитываем, чтобы «32» в форме осталось «32»,
но в байтах стало 32 TiB. Иначе алерт used/limit остаётся завышенным ~на 10%.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "e8f1a2b3c4d5"
down_revision = "6f9ee5710f34"
branch_labels = None
depends_on = None

SI_TB_BYTES = 10**12
IEC_TB_BYTES = 1024**4


def _rescale(conn, numerator: int, denominator: int) -> None:
    rows = conn.execute(
        sa.text(
            "SELECT id, hosting_traffic_limit_bytes FROM nodes "
            "WHERE hosting_traffic_limit_bytes IS NOT NULL "
            "AND hosting_traffic_limit_bytes > 0"
        )
    ).fetchall()
    update = sa.text(
        "UPDATE nodes SET hosting_traffic_limit_bytes = :value WHERE id = :id"
    )
    for node_id, value in rows:
        conn.execute(
            update,
            {"id": node_id, "value": round(int(value) * numerator / denominator)},
        )


def upgrade() -> None:
    _rescale(op.get_bind(), IEC_TB_BYTES, SI_TB_BYTES)


def downgrade() -> None:
    _rescale(op.get_bind(), SI_TB_BYTES, IEC_TB_BYTES)
