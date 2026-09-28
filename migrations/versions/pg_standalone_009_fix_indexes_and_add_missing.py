"""fix broken covering indexes and add missing FK/GIN indexes

Revision ID: pg_standalone_009
Revises: pg_standalone_008
Create Date: 2026-05-09

1. Drop broken indexes from perf_covering_indexes (wrong table/column names)
2. Recreate covering indexes with correct names
3. Add missing FK indexes for JOIN performance
4. Add GIN trgm index on order.customer for LIKE searches

实现修正（2026-09-27）
---------------------
原实现用 `connection.execute(text("COMMIT"))` 想跳出事务（CONCURRENTLY 需要），
该写法在 SQLAlchemy 2.x 下无效：`DROP INDEX CONCURRENTLY` 仍报
「cannot run inside a transaction block」，且异常被 `except Exception: pass`
吞掉，事务随之进入 aborted 状态，后续语句全部以 `InFailedSqlTransaction`
失败——整条迁移从未生效。现统一改用 `_legacy_base_guard.run_concurrently()`
（内部走 Alembic `autocommit_block()`），并对待建索引做表/列存在性过滤，
使空库重放（此时部分表列由其它分支迁移稍后建出）不会中断。
"""
from migrations._legacy_base_guard import (
    base_schema_absent,
    filter_ready,
    run_concurrently,
)

revision = 'pg_standalone_009'
down_revision = 'pg_standalone_008'
branch_labels = None
depends_on = None

# Drop broken indexes (table 'orders' doesn't exist, column 'customer_name'/'date' wrong)
DROP_BROKEN = [
    'DROP INDEX CONCURRENTLY IF EXISTS idx_perf_order_status_date_covering',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_perf_order_customer_date',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_perf_stockin_product_date',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_perf_stockout_product_date',
]

# Recreate with correct table/column names：(sql, 前置表列)
CREATE_CORRECT = [
    # Order covering indexes (table is 'order', not 'orders'; column is 'customer', not 'customer_name')
    ("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_perf_order_status_date_covering
        ON "order" (status, order_date DESC, id)
        WHERE is_deleted = false
    """, [('order', c) for c in ('status', 'order_date', 'id', 'is_deleted')]),
    ("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_perf_order_customer_date
        ON "order" (customer, order_date DESC)
        WHERE is_deleted = false
    """, [('order', c) for c in ('customer', 'order_date', 'is_deleted')]),
    # Stock covering indexes (column is stockin_date/stockout_date, not 'date')
    ("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_perf_stockin_product_date
        ON stock_in (product_id, stockin_date DESC)
    """, [('stock_in', c) for c in ('product_id', 'stockin_date')]),
    ("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_perf_stockout_product_date
        ON stock_out (product_id, stockout_date DESC)
    """, [('stock_out', c) for c in ('product_id', 'stockout_date')]),
]

# Missing FK indexes — these cause sequential scans on JOINs
FK_INDEXES = [
    # Order FK columns
    ('idx_order_locked_by', 'order', ['locked_by_id']),
    ('idx_order_deleted_by', 'order', ['deleted_by_id']),
    ('idx_order_batch_completed_by', 'order', ['batch_completed_by_id']),
    # StockReturn FK
    ('idx_stockreturn_order', 'stock_return', ['order_id']),
    # Permission self-referential FK
    ('idx_permission_parent', 'permission', ['parent_id']),
    # Approval FKs
    ('idx_approval_request_approver', 'approval_request', ['approver_id']),
    ('idx_approval_log_actor', 'approval_log', ['actor_id']),
    # Log table FKs
    ('idx_order_status_log_operator', 'order_status_log', ['operator_id']),
    ('idx_order_batch_audit_log_operator', 'order_batch_audit_log', ['operator_id']),
    ('idx_customer_access_log_customer', 'customer_access_log', ['customer_id']),
    ('idx_customer_access_log_user', 'customer_access_log', ['user_id']),
    # Material registration FKs
    ('idx_material_reg_created_by', 'material_registration', ['created_by']),
    ('idx_material_reg_item_order_item', 'material_registration_item', ['order_item_id']),
]

# GIN trgm index on order.customer for LIKE '%...%' searches
GIN_INDEXES = [
    ("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_order_customer_trgm
        ON "order" USING gin (customer gin_trgm_ops)
    """, [('order', 'customer')]),
]


def _fk_statements():
    return [
        (f'CREATE INDEX CONCURRENTLY IF NOT EXISTS {idx_name} '
         f'ON "{table}" ({", ".join(columns)})',
         [(table, c) for c in columns])
        for idx_name, table, columns in FK_INDEXES
    ]


def upgrade():
    if base_schema_absent():
        return
    run_concurrently(DROP_BROKEN)
    run_concurrently(filter_ready(CREATE_CORRECT))
    run_concurrently(filter_ready(_fk_statements()))
    run_concurrently(filter_ready(GIN_INDEXES))


def downgrade():
    if base_schema_absent():
        return

    def _idx_name(ddl):
        return ddl.split('IF NOT EXISTS')[1].split('\n')[0].strip().split()[0]

    drop_statements = (
        [f'DROP INDEX CONCURRENTLY IF EXISTS {_idx_name(ddl)}'
         for ddl, _ in GIN_INDEXES]
        + [f'DROP INDEX CONCURRENTLY IF EXISTS {name}'
           for name, _, _ in reversed(FK_INDEXES)]
        + [f'DROP INDEX CONCURRENTLY IF EXISTS {_idx_name(ddl)}'
           for ddl, _ in CREATE_CORRECT]
    )
    run_concurrently(drop_statements)
