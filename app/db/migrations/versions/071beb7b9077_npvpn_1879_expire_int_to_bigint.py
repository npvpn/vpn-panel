"""NPVPN-1879 expire int to bigint

Revision ID: 071beb7b9077
Revises: d7e9f1a2b3c4
Create Date: 2026-08-20 10:57:32.072436

`users.expire` и `next_plans.expire` в MySQL были INT, то есть верхняя граница
срока подписки — 2147483647 (2038-01-19 03:14:07). Бессрочные подписки бота
выставляют ровно этот потолок, и любое продление поверх него (реферальные дни,
бонусы) роняло UPDATE:

    (pymysql.err.DataError) (1264, "Out of range value for column 'expire' at row 1")

Панель отвечала боту 500, синк уходил в бесконечные ретраи, а сверка держала
вечное расхождение expire_drift. Независимо от этого кейса INT-потолок всё
равно упирается в 2038 год для любой годовой подписки.

Под SQLite миграция ничего не делает: там INTEGER и так 64-битный.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '071beb7b9077'
down_revision = 'd7e9f1a2b3c4'
branch_labels = None
depends_on = None

INT32_MAX = 2147483647


def upgrade() -> None:
    bind = op.get_bind()
    if bind.engine.name != 'mysql':
        return

    op.alter_column('users', 'expire',
                    existing_type=sa.Integer(),
                    type_=sa.BigInteger(),
                    existing_nullable=True)
    op.alter_column('next_plans', 'expire',
                    existing_type=sa.Integer(),
                    type_=sa.BigInteger(),
                    existing_nullable=True)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.engine.name != 'mysql':
        return

    # Значения, не влезающие обратно в INT, прижимаем к потолку: без этого
    # ALTER упал бы ровно той же ошибкой 1264, из-за которой миграция и
    # появилась. Срок при откате теряет точность, но остаётся бессрочным
    # в том же смысле, что и до миграции.
    op.execute(f"UPDATE users SET expire = {INT32_MAX} WHERE expire > {INT32_MAX}")
    op.execute(f"UPDATE next_plans SET expire = {INT32_MAX} WHERE expire > {INT32_MAX}")

    op.alter_column('next_plans', 'expire',
                    existing_type=sa.BigInteger(),
                    type_=sa.Integer(),
                    existing_nullable=True)
    op.alter_column('users', 'expire',
                    existing_type=sa.BigInteger(),
                    type_=sa.Integer(),
                    existing_nullable=True)
