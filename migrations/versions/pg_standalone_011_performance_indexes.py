"""Add performance indexes for 20k+ data optimization

Revision ID: pg_standalone_011
Revises: pg_standalone_010
Create Date: 2026-05-10
"""
from alembic import op

revision = "pg_standalone_011"
down_revision = "pg_standalone_010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        # Order: composite index for common list query pattern
        op.execute(
            'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_order_not_deleted_date '
            'ON "order" (order_date DESC) WHERE is_deleted IS NOT TRUE'
        )
        op.execute(
            'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_order_not_deleted_customer '
            'ON "order" (customer) WHERE is_deleted IS NOT TRUE'
        )

        # MaterialRegistration: indexes for list/filter/sort
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_material_reg_status "
            "ON material_registration (status)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_material_reg_date "
            "ON material_registration (registration_date DESC)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_material_reg_create_time "
            "ON material_registration (create_time DESC)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_material_reg_supplier "
            "ON material_registration (supplier_name)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_material_reg_order_no "
            "ON material_registration (purchase_order_no)"
        )

        # MaterialRegistrationItem: index for aggregation queries
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_material_reg_item_reg_id "
            "ON material_registration_item (registration_id)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_material_reg_item_reg_id")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_material_reg_order_no")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_material_reg_supplier")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_material_reg_create_time")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_material_reg_date")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_material_reg_status")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_order_not_deleted_customer")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_order_not_deleted_date")
