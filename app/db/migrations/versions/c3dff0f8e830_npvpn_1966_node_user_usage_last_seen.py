"""npvpn_1966_node_user_usage_last_seen

Revision ID: c3dff0f8e830
Revises: 071beb7b9077
Create Date: 2026-08-31 19:26:01.655958

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c3dff0f8e830"
down_revision = "071beb7b9077"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Колонка добавляется в конец таблицы, nullable и без server_default —
    # только в этом случае MySQL 8+/9 применяет ALGORITHM=INSTANT и не
    # перестраивает node_user_usages (~75M строк, 11 ГБ).
    #
    # Бэкфилла нет намеренно: у существующих строк last_seen_at IS NULL, а
    # фильтр дашборда `last_seen_at >= NOW() - INTERVAL N MINUTE` их отсекает
    # сам — таблица приходит в рабочее состояние за один тик джобы.
    op.add_column("node_user_usages", sa.Column("last_seen_at", sa.DateTime(), nullable=True))

    # Покрывающий индекс под панель «Connections by Node»: она берёт окно в два
    # часа по created_at (~400k строк) и резидуально фильтрует по last_seen_at.
    # Без него резидуальный фильтр ломает покрываемость idx_ca_node_traffic и
    # каждая строка окна превращается в PK-lookup.
    #
    # На MySQL идёт через ALTER с ALGORITHM=INPLACE, LOCK=NONE: построение на
    # ~75M строк занимает 5–20 минут, и всё это время апдейты record_user_usages
    # не блокируются. Панель на это время не поднимется — выкатывать в окно
    # низкой нагрузки.
    bind = op.get_bind()
    if bind.engine.name == "mysql":
        op.execute(
            "ALTER TABLE node_user_usages "
            "ADD INDEX idx_ca_lastseen_node_user (created_at, last_seen_at, node_id, user_id), "
            "ALGORITHM=INPLACE, LOCK=NONE"
        )
    else:
        op.create_index(
            "idx_ca_lastseen_node_user",
            "node_user_usages",
            ["created_at", "last_seen_at", "node_id", "user_id"],
            unique=False,
        )


def downgrade() -> None:
    op.drop_index("idx_ca_lastseen_node_user", table_name="node_user_usages")
    op.drop_column("node_user_usages", "last_seen_at")
