"""npvpn 1842 backfill user bot

Проставляет users.bot_id там, где он пуст, — но только на панели ровно с одним ботом.

Причина (NPVPN-1842): в режиме одного бота бот не передавал панели имя бота, юзер
сохранялся без привязки и получал настройки из переменных окружения панели вместо
админки. На opl так накопилось 109 920 юзеров из 115 319, и правка настройки в админке
доезжала до меньшинства.

Правило «ровно один бот» намеренно узкое: на мультиботовой панели владельца строки
users по ней самой не определить, а ошибиться — значит показать пользователю чужие
тексты и чужую поддержку. Там миграция не делает ничего.

Revision ID: 8a985b0c7775
Revises: c4f8a1b2d3e5
Create Date: 2026-08-14 00:21:46.497833

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = '8a985b0c7775'
down_revision = 'c4f8a1b2d3e5'
branch_labels = None
depends_on = None


def _backfill(bind) -> None:
    bot_ids = [row[0] for row in bind.execute(sa.text("SELECT id FROM bots")).fetchall()]
    if len(bot_ids) != 1:
        return
    bind.execute(sa.text("UPDATE users SET bot_id = :bot_id WHERE bot_id IS NULL"), {"bot_id": bot_ids[0]})


def upgrade() -> None:
    _backfill(op.get_bind())


def downgrade() -> None:
    # Какие именно строки были NULL, после апгрейда не восстановить, а привязка сама по
    # себе данные не портит — откат ничего не делает осознанно.
    pass
