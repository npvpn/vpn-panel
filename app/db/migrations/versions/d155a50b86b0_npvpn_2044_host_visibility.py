"""npvpn_2044_host_visibility

Видимость хоста переносится из неявного правила «пустая привязка к ботам = виден
всем» в колонку `hosts.visibility`. Поведение сохраняется байт-в-байт: кто видел
хост — видит, кто не видел — не видит.

`server_default` колонки — `restricted`, а существующим непривязанным хостам
`shared` ставится явным UPDATE ниже. Это не противоречие: миграция обязана
сохранить работающий прод, а дефолт задаёт поведение для хостов, которые заведут
после — новый хост не должен молча уйти всем партнёрам.

Revision ID: d155a50b86b0
Revises: 7c2f4a8e1b6d
Create Date: 2026-10-01 20:50:13.048132

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d155a50b86b0"
down_revision = "7c2f4a8e1b6d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "hosts",
        sa.Column("visibility", sa.String(length=16), nullable=False, server_default=sa.text("'restricted'")),
    )
    op.add_column("hosts", sa.Column("is_sellable", sa.Boolean(), nullable=False, server_default=sa.text("0")))
    op.add_column("hosts", sa.Column("catalog_price", sa.Numeric(10, 2), nullable=True))

    # Перенос текущей видимости в колонку. Непривязанный хост раздавался всем ботам
    # (app/xray/host_addresses.py:host_allowed_for_bot), значит он shared.
    # Выключенные хосты обрабатываются тем же правилом намеренно: иначе их
    # последующее включение внезапно никому ничего не даст, и разбираться будут
    # на боевом трафике.
    op.execute("UPDATE hosts SET visibility = 'shared' WHERE id NOT IN (SELECT host_id FROM host_bot_association)")
    op.execute("UPDATE hosts SET visibility = 'restricted' WHERE id IN (SELECT host_id FROM host_bot_association)")


def downgrade() -> None:
    op.drop_column("hosts", "catalog_price")
    op.drop_column("hosts", "is_sellable")
    op.drop_column("hosts", "visibility")
