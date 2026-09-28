"""添加退货功能和出货表退货累计字段

Revision ID: add_stock_return
Revises: add_app_version
Create Date: 2026-05-05
"""
import sqlalchemy as sa
from alembic import op

from migrations._legacy_base_guard import (
    base_schema_absent,
    create_index_if_columns_exist,
)

revision = 'add_stock_return'
down_revision = 'add_app_version'
branch_labels = None
depends_on = None

def upgrade():
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    # 1. stock_out 表新增 returned_quantity 列
    op.add_column(
        'stock_out',
        sa.Column('returned_quantity', sa.Integer(), nullable=False, server_default='0', comment='累计退货数量'),
    )

    # 2. 创建 stock_return 退货表
    op.create_table(
        'stock_return',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('return_no', sa.String(20), nullable=False, unique=True, comment='退货编号'),
        sa.Column('return_date', sa.DateTime(), nullable=True, comment='退货时间'),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('product.id'), nullable=False, comment='产品ID'),
        sa.Column('quantity', sa.Integer(), nullable=False, comment='退货数量'),
        sa.Column('customer', sa.String(100), nullable=True, comment='客户名称'),
        sa.Column('stockout_id', sa.Integer(), sa.ForeignKey('stock_out.id'), nullable=False, comment='关联出货ID'),
        sa.Column('order_id', sa.Integer(), sa.ForeignKey('order.id', ondelete='SET NULL'), nullable=True, comment='关联订单ID'),
        sa.Column('reason', sa.String(200), nullable=True, comment='退货原因'),
        sa.Column('note', sa.Text(), nullable=True, comment='备注'),
    )

    # 3. 创建索引
    create_index_if_columns_exist('idx_stockreturn_stockout', 'stock_return', ['stockout_id'])
    create_index_if_columns_exist('idx_stockreturn_product_date', 'stock_return', ['product_id', 'return_date'])
    create_index_if_columns_exist('idx_stockreturn_customer_date', 'stock_return', ['customer', 'return_date'])

def downgrade():
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    op.drop_index('idx_stockreturn_customer_date', table_name='stock_return', if_exists=True)
    op.drop_index('idx_stockreturn_product_date', table_name='stock_return', if_exists=True)
    op.drop_index('idx_stockreturn_stockout', table_name='stock_return', if_exists=True)
    op.drop_table('stock_return')
    op.drop_column('stock_out', 'returned_quantity')
