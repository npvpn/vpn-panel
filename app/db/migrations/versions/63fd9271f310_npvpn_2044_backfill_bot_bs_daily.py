"""npvpn_2044_backfill_bot_bs_daily

Засевает bot_bs_daily историей из node_user_usages: там непрерывный почасовой
журнал с октября 2024 (9.6 млн строк), и терять его при переходе на агрегат
незачем — после бэкфилла чистку сырого журнала можно включать.

Идёт чанками по месяцам: за 30 дней запрос ~0.7 с, а за два года одним куском
упрётся в max_execution_time = 60000 (тюнинг MySQL панели).

ОГРАНИЧЕНИЕ: nodes.is_bs — признак ТЕКУЩИЙ, истории у него нет. Если нода стала
БС позже, здесь ей припишется и прежний трафик; если перестала — потеряется.
Исторические цифры поэтому приблизительны, а всё, что агрегат пишет сам, точно.

Revision ID: 63fd9271f310
Revises: 177e3212d713
Create Date: 2026-10-02 10:30:00.000000

"""

from datetime import datetime

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "63fd9271f310"
down_revision = "177e3212d713"
branch_labels = None
depends_on = None

_INSERT = """
INSERT INTO bot_bs_daily (bot_id, node_id, day, used_bytes)
SELECT u.bot_id, nuu.node_id, DATE(nuu.created_at), SUM(nuu.used_traffic)
FROM node_user_usages nuu
JOIN nodes n ON n.id = nuu.node_id AND n.is_bs = 1
JOIN users u ON u.id = nuu.user_id
WHERE u.bot_id IS NOT NULL
  AND nuu.created_at >= :start AND nuu.created_at < :end
GROUP BY u.bot_id, nuu.node_id, DATE(nuu.created_at)
"""

# Идемпотентность: повторный прогон не должен удваивать суммы, поэтому при
# конфликте по (bot_id, node_id, day) строка НЕ меняется — первая запись
# выигрывает. Для суток, которые уже посчитала джоба, бэкфилл будет no-op.
_ON_CONFLICT_MYSQL = " ON DUPLICATE KEY UPDATE used_bytes = used_bytes"
_ON_CONFLICT_SQLITE = " ON CONFLICT (bot_id, node_id, day) DO NOTHING"


def _next_month(moment):
    return (
        moment.replace(year=moment.year + 1, month=1)
        if moment.month == 12
        else moment.replace(month=moment.month + 1)
    )


def backfill_bot_bs_daily(connection) -> int:
    """Переносит историю чанками по месяцам. Возвращает число вставленных строк."""
    dialect = connection.dialect.name
    suffix = _ON_CONFLICT_MYSQL if dialect == "mysql" else _ON_CONFLICT_SQLITE

    bounds = connection.execute(sa.text("SELECT MIN(created_at), MAX(created_at) FROM node_user_usages")).one()
    if bounds[0] is None:
        return 0

    start = bounds[0]
    last = bounds[1]
    if isinstance(start, str):
        start = datetime.fromisoformat(start)
    if isinstance(last, str):
        last = datetime.fromisoformat(last)
    start = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    written = 0
    while start <= last:
        end = _next_month(start)
        result = connection.execute(sa.text(_INSERT + suffix), {"start": start, "end": end})
        written += result.rowcount or 0
        start = end
    return written


def upgrade() -> None:
    backfill_bot_bs_daily(op.get_bind())


def downgrade() -> None:
    op.execute("DELETE FROM bot_bs_daily")
