"""add user.factory column and notification table

Revision ID: add_user_factory_and_notification
Revises: pg_standalone_018_purchase_plan_unique_month_customer
Create Date: 2026-08-04
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_user_factory_and_notification'
down_revision = 'pg_standalone_018_purchase_plan_unique_month_customer'
branch_labels = None
depends_on = None


def upgrade():
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
    op.create_index('ix_notification_user_read', 'notification', ['user_id', 'is_read'])
    op.create_index('ix_notification_created_at', 'notification', ['created_at'])
    op.create_index('ix_notification_related_order_id', 'notification', ['related_order_id'])


def downgrade():
    op.drop_index('ix_notification_related_order_id', table_name='notification')
    op.drop_index('ix_notification_created_at', table_name='notification')
    op.drop_index('ix_notification_user_read', table_name='notification')
    op.drop_table('notification')
    op.drop_column('user', 'factory')
