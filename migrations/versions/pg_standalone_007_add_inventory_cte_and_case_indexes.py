"""添加库存CTE查询和皮套搜索性能索引

为库存CTE查询添加关键复合索引，优化20K+数据量场景：
- order: (product_id, customer, order_type) - 库存CTE订单聚合
- stock_out: (product_id, customer) - 库存CTE出库聚合（stockin_id IS NULL时）
- case: GIN trgm索引 - 皮套模糊搜索

Revision ID: pg_standalone_007
Revises: pg_standalone_006
Create Date: 2026-05-05
"""
from collections.abc import Sequence

from alembic import op

from migrations._legacy_base_guard import (
    base_schema_absent,
    create_index_if_columns_exist,
)

revision: str = 'pg_standalone_007'
down_revision: str | None = 'pg_standalone_006'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    # ========================================
    # 库存CTE查询核心索引
    # 这些索引支撑 get_inventory_paginated() 的4个CTE子查询
    # ========================================

    # 订单聚合: WHERE product_id = ANY(:pids) AND customer = :sc
    # GROUP BY product_id, customer -> 需要 (product_id, customer, order_type) 覆盖
    create_index_if_columns_exist(
        'idx_order_product_customer_type', 'order',
        ['product_id', 'customer', 'order_type'],
        if_not_exists=True,
    )

    # 出库聚合: WHERE stockin_id IS NULL AND product_id = ANY(:pids)
    # AND customer = :sc -> 需要 (product_id, customer) 其中 stockin_id IS NULL
    create_index_if_columns_exist(
        'idx_stockout_product_customer_noin', 'stock_out',
        ['product_id', 'customer', 'stockin_id'],
        if_not_exists=True,
    )

    # 国家聚合: WHERE product_id = ANY(:pids) AND order_type = 'custom'
    create_index_if_columns_exist(
        'idx_order_product_type_country', 'order',
        ['product_id', 'order_type', 'country'],
        if_not_exists=True,
    )

    # ========================================
    # 皮套搜索索引
    # ========================================

    # 皮套名称/条码 GIN trgm 索引（模糊搜索优化）
    op.execute(
        'CREATE INDEX IF NOT EXISTS idx_case_name_trgm '
        "ON \"case\" USING gin (name gin_trgm_ops)"
    )
    op.execute(
        'CREATE INDEX IF NOT EXISTS idx_case_barcode_trgm '
        "ON \"case\" USING gin (barcode gin_trgm_ops)"
    )

def downgrade() -> None:
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    op.drop_index('idx_order_product_customer_type', if_exists=True)
    op.drop_index('idx_stockout_product_customer_noin', if_exists=True)
    op.drop_index('idx_order_product_type_country', if_exists=True)
    op.execute('DROP INDEX IF EXISTS idx_case_name_trgm')
    op.execute('DROP INDEX IF EXISTS idx_case_barcode_trgm')
