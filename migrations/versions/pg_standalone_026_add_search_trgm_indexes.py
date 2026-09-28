"""联想搜索索引化：为单号/模糊搜索字段补建 pg_trgm GIN 索引

Revision ID: pg_standalone_026_search_trgm
Revises: pg_standalone_025_add_cs_indexes
Create Date: 2026-08-10

补建高频 ILIKE '%keyword%' 查询字段的 pg_trgm GIN 索引：

1. 收编 apply_material_trgm_indexes.sql 的 DDL 进迁移管理（来料登记联想搜索）：
   - material_registration.supplier_name / purchase_order_no
   - purchase_order.customer_name
   - material_registration_item.material_name
2. 新增单号类联想搜索索引：
   - "order".order_no（订单查询/联想）
   - stock_in.stockin_no（备货单号搜索）
   - stock_out.stockout_no（出货单号搜索）
   - supplier.name（供应商联想）

全部使用 CREATE INDEX CONCURRENTLY IF NOT EXISTS，不锁表且幂等可重入；
与根目录 apply_material_trgm_indexes.sql 重复执行不冲突。
"""
from alembic import op
from sqlalchemy import text

from migrations._legacy_base_guard import run_concurrently, table_columns


def _ready(requirements) -> bool:
    """索引引用的表与列都齐备时才执行（空库重放中个别列可能尚未建出）。"""
    for table, column in requirements:
        present = table_columns(table)
        if present is None or column not in present:
            return False
    return True


revision = 'pg_standalone_026_search_trgm'
down_revision = 'pg_standalone_025_add_cs_indexes'
branch_labels = None
depends_on = None

# (索引名, DDL, [(表, 列)]) 列表
GIN_INDEXES = [
    # ---- 收编 apply_material_trgm_indexes.sql ----
    ('idx_material_reg_supplier_trgm',
     'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_material_reg_supplier_trgm '
     'ON material_registration USING gin (supplier_name gin_trgm_ops)',
     [('material_registration', 'supplier_name')]),
    ('idx_material_reg_order_no_trgm',
     'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_material_reg_order_no_trgm '
     'ON material_registration USING gin (purchase_order_no gin_trgm_ops)',
     [('material_registration', 'purchase_order_no')]),
    ('idx_purchase_order_customer_trgm',
     'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_purchase_order_customer_trgm '
     'ON purchase_order USING gin (customer_name gin_trgm_ops)',
     [('purchase_order', 'customer_name')]),
    ('idx_mat_reg_item_name_trgm',
     'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_mat_reg_item_name_trgm '
     'ON material_registration_item USING gin (material_name gin_trgm_ops)',
     [('material_registration_item', 'material_name')]),
    # ---- 新增单号/供应商联想索引 ----
    ('idx_order_order_no_trgm',
     'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_order_order_no_trgm '
     'ON "order" USING gin (order_no gin_trgm_ops)',
     [('order', 'order_no')]),
    ('idx_stockin_no_trgm',
     'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_stockin_no_trgm '
     'ON stock_in USING gin (stockin_no gin_trgm_ops)',
     [('stock_in', 'stockin_no')]),
    ('idx_stockout_no_trgm',
     'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_stockout_no_trgm '
     'ON stock_out USING gin (stockout_no gin_trgm_ops)',
     [('stock_out', 'stockout_no')]),
    ('idx_supplier_name_trgm',
     'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_supplier_name_trgm '
     'ON supplier USING gin (name gin_trgm_ops)',
     [('supplier', 'name')]),
]


def upgrade():
    # pg_trgm 扩展（PostgreSQL 自带；004 已启用，此处幂等兜底）
    op.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm')

    ready = [(name, ddl) for name, ddl, reqs in GIN_INDEXES if _ready(reqs)]
    if not ready:
        return
    # CONCURRENTLY 不能在事务块内运行 -> autocommit_block（历史 COMMIT hack 无效）
    with op.get_context().autocommit_block():
        for name, ddl in ready:
            # CREATE INDEX CONCURRENTLY 中途失败会留下 INVALID 索引，而 IF NOT EXISTS
            # 遇同名（即使 INVALID）会直接跳过；先检测并清理无效索引，保证重跑真正生效
            invalid = op.get_bind().execute(text(
                'SELECT 1 FROM pg_class c JOIN pg_index i ON i.indexrelid = c.oid '
                'WHERE c.relname = :name AND NOT i.indisvalid'
            ), {'name': name}).first()
            if invalid:
                op.execute(text(f"DROP INDEX CONCURRENTLY IF EXISTS {name}"))
            op.execute(text(ddl))


def downgrade():
    statements = [
        f'DROP INDEX CONCURRENTLY IF EXISTS {name}'
        for name, _ddl, _reqs in reversed(GIN_INDEXES)
    ]
    run_concurrently(statements)
    # 注意：不删除 pg_trgm 扩展，其他索引/功能依赖它
