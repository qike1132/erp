"""Change order status to nullable with None default

Revision ID: a8f3c2d1e5b7
Revises: 659467a97350
Create Date: 2026-04-28 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a8f3c2d1e5b7'
down_revision = '659467a97350'
branch_labels = None
depends_on = None


def upgrade():
    # 1. 清除已废弃的状态值，统一设为 NULL
    op.execute("UPDATE `order` SET status=NULL WHERE status IN ('待备货', '部分备货', '已备货')")
    # 2. 将 status 列改为 nullable，默认值改为 NULL
    op.alter_column('order', 'status',
                    existing_type=sa.String(20),
                    nullable=True,
                    existing_server_default='待备货',
                    server_default=None)
    # 3. 为 purchase_order.source_order_id 添加索引（采购中心查询性能关键）
    op.create_index('idx_purchase_order_source_order_id', 'purchase_order', ['source_order_id'])


def downgrade():
    op.drop_index('idx_purchase_order_source_order_id', table_name='purchase_order')
    # 将 NULL 状态回退为'待备货'再改回 NOT NULL
    op.execute("UPDATE `order` SET status='待备货' WHERE status IS NULL")
    op.alter_column('order', 'status',
                    existing_type=sa.String(20),
                    nullable=False,
                    server_default='待备货')
