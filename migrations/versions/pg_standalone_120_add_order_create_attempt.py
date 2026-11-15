"""新增订单创建幂等登记表（``POST /orders/create`` 请求级幂等 P0）

Revision ID: pg_standalone_120_add_order_create_attempt
Revises: pg_standalone_119_add_po_item_role_id
Create Date: 2026-11-15

仅新增 order_create_attempt（表 + 唯一约束 + created_at 索引），不修改订单、
库存流水或任何既有索引；登记与订单写入在同一事务提交。
downgrade 只删除本迁移新建的对象。
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = 'pg_standalone_120_add_order_create_attempt'
down_revision = 'pg_standalone_119_add_po_item_role_id'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'order_create_attempt',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('actor_id', sa.Integer(), nullable=False, comment='发起下单的用户ID'),
        sa.Column(
            'idempotency_key', sa.String(length=64), nullable=False,
            comment='客户端幂等键（Idempotency-Key 头）',
        ),
        sa.Column(
            'request_hash', sa.String(length=64), nullable=False,
            comment='下单内容指纹（同键不同内容即 409）',
        ),
        sa.Column(
            'response_body', postgresql.JSONB(astext_type=sa.Text()), nullable=True,
            comment='首次成功响应体（重放用）',
        ),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['actor_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'actor_id', 'idempotency_key',
            name='uq_order_create_attempt_actor_key',
        ),
    )
    # 键有过期语义：历史键按时间裁剪，避免清理时全表扫。
    op.create_index(
        'idx_order_create_attempt_created_at', 'order_create_attempt', ['created_at'],
    )


def downgrade() -> None:
    op.drop_index('idx_order_create_attempt_created_at', table_name='order_create_attempt')
    op.drop_table('order_create_attempt')
