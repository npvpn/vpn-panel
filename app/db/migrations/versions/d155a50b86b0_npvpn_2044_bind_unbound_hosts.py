"""npvpn_2044_bind_unbound_hosts

Непривязанный хост раздавался всем ботам (прежний фолбэк в
app/xray/host_addresses.py:host_allowed_for_bot). Теперь доступ определяется
только привязкой, поэтому поведение сохраняется явными привязками: каждый
непривязанный хост привязывается ко всем ботам своей панели.

Выключенные хосты (is_disabled) привязываются тем же правилом намеренно: иначе
их последующее включение внезапно никому ничего не даст, и разбираться будут на
боевом трафике.

downgrade НЕ удаляет привязки: отличить созданные здесь от сделанных руками
нечем, а помечать их колонкой ради откатного пути, которым пользуются раз в
жизни, дороже. При откате кода лишние привязки безвредны — прежний предикат
отдавал такой хост всем ботам и так.

Revision ID: d155a50b86b0
Revises: 7c2f4a8e1b6d
Create Date: 2026-10-01 20:50:13.048132

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "d155a50b86b0"
down_revision = "7c2f4a8e1b6d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO host_bot_association (host_id, bot_id) "
        "SELECT h.id, b.id FROM hosts h CROSS JOIN bots b "
        "WHERE NOT EXISTS (SELECT 1 FROM host_bot_association a WHERE a.host_id = h.id)"
    )


def downgrade() -> None:
    pass
