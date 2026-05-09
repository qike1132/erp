"""add updated_at to all tables

Revision ID: add_updated_at
Revises:
Create Date: 2026-05-06
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_updated_at'
down_revision = '659467a97350'
branch_labels = None
depends_on = None

TABLES = [
    'product', 'order', 'stock_in', 'stock_out', 'stock_return',
    'inventory_log', 'case', 'case_stock_in', 'case_stock_out',
    'case_inventory_log', 'permission', 'app_version', 'craft_work',
    'daily_production_record', 'packaging_record', 'order_status_log',
    'customer_access_log', 'modification_log', 'saved_query',
    'approval_request', 'approval_log', 'purchase_order_item',
    'shipment_records', 'purchase_plan_details', 'production_plan_log',
    'staging_purchase_plan', 'order_sync_record',
]

def upgrade() -> None:
    # Create trigger function first (CREATE OR REPLACE is idempotent)
    op.execute("""
        CREATE OR REPLACE FUNCTION trigger_set_updated_at()
        RETURNS TRIGGER AS $
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $ LANGUAGE plpgsql;
    """)
    # Add updated_at column only if it doesn't already exist
    for table in TABLES:
        op.execute(f"""
            DO $
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = '{table}' AND column_name = 'updated_at'
                ) THEN
                    ALTER TABLE "{table}" ADD COLUMN updated_at TIMESTAMP WITHOUT TIME ZONE;
                END IF;
            END$;
        """)
    # Create triggers only if they don't already exist
    for table in TABLES:
        op.execute(f"""
            DO $
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_trigger WHERE tgname = 'set_updated_at' AND tgrelid = '{table}'::regclass
                ) THEN
                    CREATE TRIGGER set_updated_at
                        BEFORE UPDATE ON "{table}"
                        FOR EACH ROW
                        EXECUTE FUNCTION trigger_set_updated_at();
                END IF;
            END$;
        """)

def downgrade() -> None:
    for table in TABLES:
        op.execute(f'DROP TRIGGER IF EXISTS set_updated_at ON "{table}"')
    op.execute('DROP FUNCTION IF EXISTS trigger_set_updated_at()')
    for table in TABLES:
        op.drop_column(table, 'updated_at')
