"""npvpn-2072 journal and pins

Revision ID: f9cc88485133
Revises: d8fad3e7f98b
Create Date: 2026-09-18 13:54:40.561199

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f9cc88485133'
down_revision = 'd8fad3e7f98b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'host_composition_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('epoch_index', sa.Integer(), nullable=False),
        # Без ForeignKeyConstraint (I3, NPVPN-2072, финальное ревью): архив
        # журнала обязан пережить удаление хоста — FK с CASCADE стирал бы
        # снимки состава вместе с ним, и локация молча исчезала бы из истории
        # вместо явной пометки. host_id намеренно может "повиснуть".
        sa.Column('host_id', sa.Integer(), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('epoch_index', 'host_id', name='uq_host_composition_snapshots'),
    )
    op.create_index(
        op.f('ix_host_composition_snapshots_epoch_index'),
        'host_composition_snapshots', ['epoch_index'], unique=False,
    )
    op.create_index(
        op.f('ix_host_composition_snapshots_host_id'),
        'host_composition_snapshots', ['host_id'], unique=False,
    )
    op.create_table(
        'user_node_pins',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('host_id', sa.Integer(), nullable=False),
        sa.Column('node_ids', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('created_by', sa.String(length=64), nullable=False),
        sa.Column('note', sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(
            ['host_id'], ['hosts.id'],
            name='fk_user_node_pins_host_id_hosts',
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.id'],
            name='fk_user_node_pins_user_id_users',
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_user_node_pins_host_id'), 'user_node_pins', ['host_id'], unique=False)
    op.create_index(op.f('ix_user_node_pins_user_id'), 'user_node_pins', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_user_node_pins_user_id'), table_name='user_node_pins')
    op.drop_index(op.f('ix_user_node_pins_host_id'), table_name='user_node_pins')
    op.drop_table('user_node_pins')
    op.drop_index(op.f('ix_host_composition_snapshots_host_id'), table_name='host_composition_snapshots')
    op.drop_index(op.f('ix_host_composition_snapshots_epoch_index'), table_name='host_composition_snapshots')
    op.drop_table('host_composition_snapshots')
