"""add_performance_indexes

添加性能优化索引，覆盖高频查询场景。

Revision ID: pg_standalone_003
Revises: pg_standalone_002
Create Date: 2026-04-22
"""
from collections.abc import Sequence

from alembic import op

revision: str = 'pg_standalone_003'
down_revision: str | None = 'pg_standalone_002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ========================================
    # 订单查询索引
    # ========================================

    # 订单客户搜索（模糊查询优化）
    op.create_index('idx_order_customer', 'order', ['customer'])

    # 订单状态+创建时间复合索引（列表页常用排序）
    op.create_index('idx_order_status_order_date', 'order', ['status', 'order_date'])

    # 订单产品+状态复合索引（产品订单列表筛选）
    op.create_index('idx_order_product_status', 'order', ['product_id', 'status'])

    # 订单类型索引（定制/常规订单筛选）
    op.create_index('idx_order_order_type', 'order', ['order_type'])

    # ========================================
    # 库存查询索引
    # ========================================

    # 入库产品+日期复合索引（入库历史查询）
    op.create_index('idx_stockin_product_date', 'stock_in', ['product_id', 'stockin_date'])

    # 出库产品+日期复合索引（出库历史查询）
    op.create_index('idx_stockout_product_date', 'stock_out', ['product_id', 'stockout_date'])

    # 入库客户搜索
    op.create_index('idx_stockin_customer', 'stock_in', ['customer'])

    # 出库客户搜索
    op.create_index('idx_stockout_customer', 'stock_out', ['customer'])

    # ========================================
    # 产品查询索引
    # ========================================

    # 产品条码搜索
    op.create_index('idx_product_barcode', 'product', ['barcode'])

    # 产品名称搜索（BOM 查询常用）
    op.create_index('idx_product_name', 'product', ['name'])

    # ========================================
    # 客户查询索引
    # ========================================

    # 客户名称搜索
    op.create_index('idx_customer_name', 'customer', ['name'])

    # ========================================
    # 采购中心索引
    # ========================================

    # 采购订单状态+创建日期
    op.create_index('idx_purchase_order_status_created', 'purchase_order', ['status', 'created_at'])

    # 采购订单供应商+状态
    op.create_index('idx_purchase_order_supplier_status', 'purchase_order', ['supplier_id', 'status'])

    # 采购订单客户统计
    op.create_index('idx_purchase_order_customer', 'purchase_order', ['customer'])


def downgrade() -> None:
    op.drop_index('idx_purchase_order_customer', table_name='purchase_order')
    op.drop_index('idx_purchase_order_supplier_status', table_name='purchase_order')
    op.drop_index('idx_purchase_order_status_created', table_name='purchase_order')
    op.drop_index('idx_customer_name', table_name='customer')
    op.drop_index('idx_product_name', table_name='product')
    op.drop_index('idx_product_barcode', table_name='product')
    op.drop_index('idx_stockout_customer', table_name='stock_out')
    op.drop_index('idx_stockin_customer', table_name='stock_in')
    op.drop_index('idx_stockout_product_date', table_name='stock_out')
    op.drop_index('idx_stockin_product_date', table_name='stock_in')
    op.drop_index('idx_order_order_type', table_name='order')
    op.drop_index('idx_order_product_status', table_name='order')
    op.drop_index('idx_order_status_order_date', table_name='order')
    op.drop_index('idx_order_customer', table_name='order')
