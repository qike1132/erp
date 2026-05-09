"""fix broken covering indexes and add missing FK/GIN indexes

Revision ID: pg_standalone_009
Revises: pg_standalone_008
Create Date: 2026-05-09

1. Drop broken indexes from perf_covering_indexes (wrong table/column names)
2. Recreate covering indexes with correct names
3. Add missing FK indexes for JOIN performance
4. Add GIN trgm index on order.customer for LIKE searches
"""

from alembic import op
from sqlalchemy import text

revision = 'pg_standalone_009'
down_revision = 'pg_standalone_008'
branch_labels = None
depends_on = None

# Drop broken indexes (table 'orders' doesn't exist, column 'customer_name'/'date' wrong)
DROP_BROKEN = [
    "DROP INDEX CONCURRENTLY IF EXISTS idx_perf_order_status_date_covering",
    "DROP INDEX CONCURRENTLY IF EXISTS idx_perf_order_customer_date",
    "DROP INDEX CONCURRENTLY IF EXISTS idx_perf_stockin_product_date",
    "DROP INDEX CONCURRENTLY IF EXISTS idx_perf_stockout_product_date",
]

# Recreate with correct table/column names
CREATE_CORRECT = [
    # Order covering indexes (table is 'order', not 'orders'; column is 'customer', not 'customer_name')
    """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_perf_order_status_date_covering
        ON "order" (status, order_date DESC, id)
        WHERE is_deleted = false
    """,
    """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_perf_order_customer_date
        ON "order" (customer, order_date DESC)
        WHERE is_deleted = false
    """,
    # Stock covering indexes (column is stockin_date/stockout_date, not 'date')
    """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_perf_stockin_product_date
        ON stock_in (product_id, stockin_date DESC)
    """,
    """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_perf_stockout_product_date
        ON stock_out (product_id, stockout_date DESC)
    """,
]

# Missing FK indexes — these cause sequential scans on JOINs
FK_INDEXES = [
    # Order FK columns
    ("idx_order_locked_by", "order", ["locked_by_id"]),
    ("idx_order_deleted_by", "order", ["deleted_by_id"]),
    ("idx_order_batch_completed_by", "order", ["batch_completed_by_id"]),
    # StockReturn FK
    ("idx_stockreturn_order", "stock_return", ["order_id"]),
    # Permission self-referential FK
    ("idx_permission_parent", "permission", ["parent_id"]),
    # Approval FKs
    ("idx_approval_request_approver", "approval_request", ["approver_id"]),
    ("idx_approval_log_actor", "approval_log", ["actor_id"]),
    # Log table FKs
    ("idx_order_status_log_operator", "order_status_log", ["operator_id"]),
    ("idx_order_batch_audit_log_operator", "order_batch_audit_log", ["operator_id"]),
    ("idx_customer_access_log_customer", "customer_access_log", ["customer_id"]),
    ("idx_customer_access_log_user", "customer_access_log", ["user_id"]),
    # Material registration FKs
    ("idx_material_reg_created_by", "material_registration", ["created_by"]),
    ("idx_material_reg_item_order_item", "material_registration_item", ["order_item_id"]),
]

# GIN trgm index on order.customer for LIKE '%...%' searches
GIN_INDEXES = [
    """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_order_customer_trgm
        ON "order" USING gin (customer gin_trgm_ops)
    """,
]


def upgrade():
    connection = op.get_bind()
    connection.execute(text("COMMIT"))

    # 1. Drop broken indexes
    for ddl in DROP_BROKEN:
        try:
            connection.execute(text(ddl))
        except Exception:
            pass  # Index may not exist if migration never ran

    # 2. Create correct covering indexes
    for ddl in CREATE_CORRECT:
        connection.execute(text(ddl))

    # 3. Add FK indexes
    for idx_name, table, columns in FK_INDEXES:
        cols = ", ".join(columns)
        connection.execute(text(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {idx_name} ON {table} ({cols})"
        ))

    # 4. Add GIN trgm indexes
    for ddl in GIN_INDEXES:
        connection.execute(text(ddl))


def downgrade():
    connection = op.get_bind()
    connection.execute(text("COMMIT"))

    for ddl in GIN_INDEXES:
        idx_name = ddl.split("IF NOT EXISTS")[1].split("\n")[0].strip().split()[0]
        connection.execute(text(f"DROP INDEX CONCURRENTLY IF EXISTS {idx_name}"))

    for idx_name, _, _ in reversed(FK_INDEXES):
        connection.execute(text(f"DROP INDEX CONCURRENTLY IF EXISTS {idx_name}"))

    for ddl in CREATE_CORRECT:
        idx_name = ddl.split("IF NOT EXISTS")[1].split("\n")[0].strip().split()[0]
        connection.execute(text(f"DROP INDEX CONCURRENTLY IF EXISTS {idx_name}"))
