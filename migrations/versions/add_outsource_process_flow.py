"""外发工序：新增发货/收货流水表，支持分批多次发货/收货

Revision ID: add_outsource_process_flow
Revises: add_outsource_ship_receive
Create Date: 2026-08-20

- 新增 order_outsource_process_flow（每次发/收一条记录）
- 存量回填：已发货/已收货工序各补一条 ship/receive 流水（按累计值 + 实际时间，操作人置空）
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'add_outsource_process_flow'
down_revision = 'add_outsource_ship_receive'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'order_outsource_process_flow',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('process_id', sa.Integer(), sa.ForeignKey('order_outsource_process.id', ondelete='CASCADE'), nullable=False),
        sa.Column('action', sa.String(length=10), nullable=False, comment='动作：ship=发货 / receive=收货'),
        sa.Column('quantity', sa.Integer(), nullable=False, comment='本次数量'),
        sa.Column('operator', sa.String(length=50), nullable=True, comment='操作人'),
        sa.Column('create_time', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True, comment='操作时间'),
        sa.Index('ix_oospf_process_time', 'process_id', 'create_time'),
    )
    op.create_index('ix_order_outsource_process_flow_process_id', 'order_outsource_process_flow', ['process_id'])
    op.create_index('ix_order_outsource_process_flow_create_time', 'order_outsource_process_flow', ['create_time'])

    # 存量回填：已发货（含已收货）工序补一条 ship 流水；已收货工序再补一条 receive 流水
    op.execute(sa.text(
        """
        INSERT INTO order_outsource_process_flow (process_id, action, quantity, operator, create_time)
        SELECT id, 'ship', shipped_quantity, NULL, actual_start_time
        FROM order_outsource_process
        WHERE status IN ('shipped', 'received') AND shipped_quantity IS NOT NULL AND shipped_quantity > 0
        """
    ))
    op.execute(sa.text(
        """
        INSERT INTO order_outsource_process_flow (process_id, action, quantity, operator, create_time)
        SELECT id, 'receive', received_quantity, NULL, actual_end_time
        FROM order_outsource_process
        WHERE status = 'received' AND received_quantity IS NOT NULL AND received_quantity > 0
        """
    ))


def downgrade():
    op.drop_table('order_outsource_process_flow')
