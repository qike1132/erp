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


revision = 'pg_standalone_026_search_trgm'
down_revision = 'pg_standalone_025_add_cs_indexes'
branch_labels = None
depends_on = None

# (索引名, DDL) 列表
GIN_INDEXES = [
    # ---- 收编 apply_material_trgm_indexes.sql ----
    ('idx_material_reg_supplier_trgm',
     'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_material_reg_supplier_trgm '
     'ON material_registration USING gin (supplier_name gin_trgm_ops)'),
    ('idx_material_reg_order_no_trgm',
     'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_material_reg_order_no_trgm '
     'ON material_registration USING gin (purchase_order_no gin_trgm_ops)'),
    ('idx_purchase_order_customer_trgm',
     'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_purchase_order_customer_trgm '
     'ON purchase_order USING gin (customer_name gin_trgm_ops)'),
    ('idx_mat_reg_item_name_trgm',
     'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_mat_reg_item_name_trgm '
     'ON material_registration_item USING gin (material_name gin_trgm_ops)'),
    # ---- 新增单号/供应商联想索引 ----
    ('idx_order_order_no_trgm',
     'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_order_order_no_trgm '
     'ON "order" USING gin (order_no gin_trgm_ops)'),
    ('idx_stockin_no_trgm',
     'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_stockin_no_trgm '
     'ON stock_in USING gin (stockin_no gin_trgm_ops)'),
    ('idx_stockout_no_trgm',
     'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_stockout_no_trgm '
     'ON stock_out USING gin (stockout_no gin_trgm_ops)'),
    ('idx_supplier_name_trgm',
     'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_supplier_name_trgm '
     'ON supplier USING gin (name gin_trgm_ops)'),
]


def upgrade():
    # pg_trgm 扩展（PostgreSQL 自带；004 已启用，此处幂等兜底）
    op.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm')

    # CONCURRENTLY 不能在事务内执行，先提交当前迁移事务（同 009 模式）
    connection = op.get_bind()
    connection.execute(text("COMMIT"))

    for name, ddl in GIN_INDEXES:
        # CREATE INDEX CONCURRENTLY 中途失败会留下 INVALID 索引，而 IF NOT EXISTS
        # 遇同名（即使 INVALID）会直接跳过；先检测并清理无效索引，保证重跑真正生效
        invalid = connection.execute(text(
            'SELECT 1 FROM pg_class c JOIN pg_index i ON i.indexrelid = c.oid '
            'WHERE c.relname = :name AND NOT i.indisvalid'
        ), {'name': name}).first()
        if invalid:
            connection.execute(text(f"DROP INDEX CONCURRENTLY IF EXISTS {name}"))
        connection.execute(text(ddl))


def downgrade():
    connection = op.get_bind()
    connection.execute(text("COMMIT"))

    for name, _ddl in reversed(GIN_INDEXES):
        connection.execute(text(f"DROP INDEX CONCURRENTLY IF EXISTS {name}"))
    # 注意：不删除 pg_trgm 扩展，其他索引/功能依赖它
