"""host balancing settings and entry nodes

Revision ID: e52ac058ffa1
Revises: b47f383fbc9b
Create Date: 2026-10-22 17:10:41.922926

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e52ac058ffa1'
down_revision = 'b47f383fbc9b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("hosts", sa.Column("balancing", sa.JSON(), nullable=True))
    op.add_column("hosts", sa.Column("balancer_nodes_source", sa.String(16), nullable=False, server_default="host"))
    op.create_table("host_balancer_nodes",
        sa.Column("host_id", sa.Integer(), sa.ForeignKey("hosts.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("node_id", sa.Integer(), sa.ForeignKey("nodes.id", ondelete="CASCADE"), primary_key=True))
    op.create_index("ix_host_balancer_nodes_node_id", "host_balancer_nodes", ["node_id"])


def downgrade() -> None:
    op.drop_table("host_balancer_nodes")
    op.drop_column("hosts", "balancer_nodes_source")
    op.drop_column("hosts", "balancing")
