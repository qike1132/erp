"""Add performance covering indexes

Revision ID: perf_idx_001
Revises: 659467a97350
Create Date: 2026-05-05

"""
from alembic import op
from sqlalchemy import text

revision = 'perf_idx_001'
down_revision = '659467a97350'
branch_labels = None
depends_on = None

INDEXES_UP = [
    """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_perf_order_status_date_covering
        ON orders (status, order_date DESC, id)
        WHERE is_deleted = false
    """,
    """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_perf_order_customer_date
        ON orders (customer_name, order_date DESC)
        WHERE is_deleted = false
    """,
    """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_perf_stockin_product_date
        ON stock_in (product_id, date DESC)
    """,
    """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_perf_stockout_product_date
        ON stock_out (product_id, date DESC)
    """,
    """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_perf_po_status_date_covering
        ON purchase_order (status, order_date DESC, id)
    """,
    """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_perf_poi_order_include
        ON purchase_order_item (order_id)
        INCLUDE (material_name, quantity, unit_price)
    """,
    """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_perf_product_name_date
        ON product (create_time DESC, id)
    """,
]

INDEXES_DOWN = [
    "DROP INDEX CONCURRENTLY IF EXISTS idx_perf_product_name_date",
    "DROP INDEX CONCURRENTLY IF EXISTS idx_perf_poi_order_include",
    "DROP INDEX CONCURRENTLY IF EXISTS idx_perf_po_status_date_covering",
    "DROP INDEX CONCURRENTLY IF EXISTS idx_perf_stockout_product_date",
    "DROP INDEX CONCURRENTLY IF EXISTS idx_perf_stockin_product_date",
    "DROP INDEX CONCURRENTLY IF EXISTS idx_perf_order_customer_date",
    "DROP INDEX CONCURRENTLY IF EXISTS idx_perf_order_status_date_covering",
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
