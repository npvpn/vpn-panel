"""npvpn-2072 address subset

Revision ID: d8fad3e7f98b
Revises: 6f9ee5710f34
Create Date: 2026-09-17 20:31:57.503271

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd8fad3e7f98b'
down_revision = '6f9ee5710f34'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'node_weight_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('epoch_index', sa.Integer(), nullable=False),
        sa.Column('node_id', sa.Integer(), nullable=False),
        sa.Column('weight', sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ['node_id'], ['nodes.id'],
            name='fk_node_weight_snapshots_node_id_nodes',
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('epoch_index', 'node_id', name='uq_node_weight_snapshots'),
    )
    op.create_index(
        op.f('ix_node_weight_snapshots_epoch_index'), 'node_weight_snapshots', ['epoch_index'], unique=False
    )
    op.create_index(op.f('ix_node_weight_snapshots_node_id'), 'node_weight_snapshots', ['node_id'], unique=False)
    op.add_column('nodes', sa.Column('hosting_used_bytes', sa.BigInteger(), nullable=True))
    op.add_column('nodes', sa.Column('hosting_used_at', sa.DateTime(), nullable=True))
    op.add_column(
        'users', sa.Column('address_rotation_offset', sa.Integer(), server_default=sa.text('0'), nullable=False)
    )


def downgrade() -> None:
    op.drop_column('users', 'address_rotation_offset')
    op.drop_column('nodes', 'hosting_used_at')
    op.drop_column('nodes', 'hosting_used_bytes')
    op.drop_index(op.f('ix_node_weight_snapshots_node_id'), table_name='node_weight_snapshots')
    op.drop_index(op.f('ix_node_weight_snapshots_epoch_index'), table_name='node_weight_snapshots')
    op.drop_table('node_weight_snapshots')
