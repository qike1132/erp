"""Add missing FK indexes and drop duplicate indexes

Revision ID: pg_standalone_010
Revises: pg_standalone_009
Create Date: 2026-05-10
"""
from alembic import op
import sqlalchemy as sa

revision = "pg_standalone_010"
down_revision = "pg_standalone_009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # CONCURRENTLY cannot run inside a transaction — use autocommit block
    with op.get_context().autocommit_block():
        # --- Add missing FK indexes ---
        op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_product_fabric_supplier ON product_fabric (supplier_id)")
        op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_product_material_supplier ON product_material (supplier_id)")
        op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_product_accessory_supplier ON product_accessory (supplier_id)")
        op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_product_packaging_supplier ON product_packaging (supplier_id)")
        op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_staging_order_product ON staging_order (product_id)")
        op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_staging_stockin_product ON staging_stock_in (product_id)")
        op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_staging_stockout_product ON staging_stock_out (product_id)")
        op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_order_sync_config_updated_by ON order_sync_config (updated_by_id)")
        op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_modification_log_modifier ON modification_log (modifier_id)")

        # --- Drop duplicate indexes (already created by model-level index=True / unique=True) ---
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_order_customer")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_product_barcode")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_product_name")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_customer_name")

        # --- Add recommended composite indexes ---
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_stockout_order_stockin_qty "
            "ON stock_out (order_id, stockin_id) INCLUDE (quantity, returned_quantity)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_stockout_deduction "
            "ON stock_out (product_id, stockout_date DESC) WHERE stockin_id IS NOT NULL"
        )
        op.execute(
            'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_order_batch_completed '
            'ON "order" (batch_completed_at DESC) WHERE batch_completed_at IS NOT NULL'
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_po_status_date_covering "
            "ON purchase_order (status, create_time DESC, id) INCLUDE (order_no, supplier_name, customer_name)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        # Composite indexes
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_po_status_date_covering")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_order_batch_completed")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_stockout_deduction")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_stockout_order_stockin_qty")

        # Re-create dropped duplicate indexes (if needed for rollback)
        op.execute("CREATE INDEX IF NOT EXISTS idx_customer_name ON customer (name)")
        op.execute("CREATE INDEX IF NOT EXISTS idx_product_name ON product (name)")
        op.execute("CREATE INDEX IF NOT EXISTS idx_product_barcode ON product (barcode)")
        op.execute("CREATE INDEX IF NOT EXISTS idx_order_customer ON \"order\" (customer)")

        # Remove FK indexes
        op.execute("DROP INDEX IF EXISTS idx_modification_log_modifier")
        op.execute("DROP INDEX IF EXISTS idx_order_sync_config_updated_by")
        op.execute("DROP INDEX IF EXISTS idx_staging_stockout_product")
        op.execute("DROP INDEX IF EXISTS idx_staging_stockin_product")
        op.execute("DROP INDEX IF EXISTS idx_staging_order_product")
        op.execute("DROP INDEX IF EXISTS idx_product_packaging_supplier")
        op.execute("DROP INDEX IF EXISTS idx_product_accessory_supplier")
        op.execute("DROP INDEX IF EXISTS idx_product_material_supplier")
        op.execute("DROP INDEX IF EXISTS idx_product_fabric_supplier")
