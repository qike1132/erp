"""Add missing performance indexes for StockOut, InventoryLog, and Order

Revision ID: add_missing_perf_idx
Revises: perf_idx_001
Create Date: 2026-06-06

"""
from alembic import op
from sqlalchemy import text

revision = 'add_missing_perf_idx'
down_revision = 'perf_idx_001'
branch_labels = None
depends_on = None

INDEXES_UP = [
    # StockOut 订单关联查询
    """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_stockout_order_stockin
        ON stock_out (order_id, stockin_id)
        WHERE stockin_id IS NOT NULL
    """,
    # InventoryLog 按产品查询
    """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_inventory_log_product_time
        ON inventory_log (product_id, create_time DESC)
    """,
    # Order 深翻页组合游标索引
    """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_order_date_id_desc
        ON "order" (order_date DESC, id DESC)
        WHERE is_deleted IS NOT TRUE
    """,
]

INDEXES_DOWN = [
    "DROP INDEX CONCURRENTLY IF EXISTS idx_order_date_id_desc",
    "DROP INDEX CONCURRENTLY IF EXISTS idx_inventory_log_product_time",
    "DROP INDEX CONCURRENTLY IF EXISTS idx_stockout_order_stockin",
]


def upgrade():
    connection = op.get_bind()
    connection.execute(text("COMMIT"))
    for ddl in INDEXES_UP:
        connection.execute(text(ddl))


def downgrade():
    connection = op.get_bind()
    connection.execute(text("COMMIT"))
    for ddl in INDEXES_DOWN:
        connection.execute(text(ddl))