"""add user.factory column and notification table

Revision ID: add_user_factory_and_notification
Revises: pg_standalone_018_purchase_plan_unique_month_customer
Create Date: 2026-08-04
"""
import sqlalchemy as sa
from alembic import op

from migrations._legacy_base_guard import (
    base_schema_absent,
    create_index_if_columns_exist,
)

revision = 'add_user_factory_and_notification'
down_revision = 'pg_standalone_018_purchase_plan_unique_month_customer'
branch_labels = None
depends_on = None

def upgrade():
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    # 1. User 表新增 factory 字段
    op.add_column('user', sa.Column('factory', sa.String(length=20), nullable=True, comment='所属工厂：滨发/贝乐/NULL'))
    # 2. 创建 notification 表
    op.create_table(
        'notification',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('type', sa.String(30), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('related_order_id', sa.Integer(), sa.ForeignKey('order.id'), nullable=True),
        sa.Column('is_read', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    create_index_if_columns_exist('ix_notification_user_read', 'notification', ['user_id', 'is_read'])
    create_index_if_columns_exist('ix_notification_created_at', 'notification', ['created_at'])
    create_index_if_columns_exist('ix_notification_related_order_id', 'notification', ['related_order_id'])

def downgrade():
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    op.drop_index('ix_notification_related_order_id', table_name='notification', if_exists=True)
    op.drop_index('ix_notification_created_at', table_name='notification', if_exists=True)
    op.drop_index('ix_notification_user_read', table_name='notification', if_exists=True)
    op.drop_table('notification')
    op.drop_column('user', 'factory')
