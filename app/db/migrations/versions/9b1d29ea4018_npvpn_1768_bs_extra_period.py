"""npvpn 1768 bs extra period

Revision ID: 9b1d29ea4018
Revises: 5d34e433db0c
Create Date: 2026-08-01 20:42:13.096639

"""
import json
from datetime import datetime

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = '9b1d29ea4018'
down_revision = '5d34e433db0c'
branch_labels = None
depends_on = None


def _bot_limits(bind):
    """{bot_id: bs_monthly_limit} из JSON-настроек ботов.

    JSON-колонку драйвер отдаёт по-разному: dict (десериализовано), str или bytes —
    последнее нельзя отдавать в payload.get, иначе миграция падает на проде.
    """
    limits = {}
    for bot_id, data in bind.execute(sa.text("SELECT bot_id, data FROM bot_settings")).fetchall():
        if isinstance(data, (bytes, bytearray)):
            data = data.decode("utf-8")
        payload = json.loads(data) if isinstance(data, str) else (data or {})
        limits[bot_id] = int(payload.get("bs_monthly_limit") or 0)
    return limits


def _backfill(bind) -> None:
    """Возвращает объём, съеденный непрерывным списанием: bs_extra += max(0, used - база).

    Восстанавливать нужно только текущий месяц: списания прошлых месяцев были
    корректным переносом остатка.

    Идемпотентно: guard `bs_extra_period IS NULL OR bs_extra_period <> :period` не даёт
    повторному вызову (ручная верификация, ретрай после частичного сбоя) забрать уже
    восстановленных пользователей ещё раз. Инкремент `bs_extra = bs_extra + :delta`
    выполняется прямо в SQL одним UPDATE, а не через read-modify-write в Python, чтобы
    не терять параллельные изменения `bs_extra` между SELECT и UPDATE (lost update).
    """
    period = datetime.utcnow().strftime("%Y-%m")
    limits = _bot_limits(bind)
    rows = bind.execute(
        sa.text(
            "SELECT u.id AS id, u.bot_id AS bot_id, "
            "COALESCE(("
            "  SELECT SUM(b.monthly_used) FROM node_user_bs_usage b "
            "  JOIN nodes n ON n.id = b.node_id "
            "  WHERE b.user_id = u.id AND b.monthly_period = :period AND n.is_bs = 1"
            "), 0) AS used "
            "FROM users u WHERE u.bs_extra IS NOT NULL "
            "AND (u.bs_extra_period IS NULL OR u.bs_extra_period <> :period)"
        ),
        {"period": period},
    ).fetchall()

    params = []
    for row in rows:
        limit = limits.get(row.bot_id, 0)
        delta = max(0, int(row.used or 0) - limit) if limit else 0
        params.append({"delta": delta, "period": period, "uid": row.id})

    # Апдейт идёт пачками по 500 только чтобы не собирать один гигантский executemany:
    # коммитов между пачками нет и быть не может — alembic держит всю миграцию в одной
    # транзакции, так что длину транзакции чанки не уменьшают.
    for chunk_start in range(0, len(params), 500):
        chunk = params[chunk_start : chunk_start + 500]
        bind.execute(
            sa.text("UPDATE users SET bs_extra = bs_extra + :delta, bs_extra_period = :period WHERE id = :uid"),
            chunk,
        )


def upgrade() -> None:
    op.add_column("users", sa.Column("bs_extra_period", sa.String(7), nullable=True))
    _backfill(op.get_bind())


def downgrade() -> None:
    # bs_extra назад не пересчитываем: откат схемы не должен повторно забирать оплаченный трафик.
    op.drop_column("users", "bs_extra_period")
