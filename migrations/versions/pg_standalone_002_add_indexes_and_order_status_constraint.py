"""add_indexes_and_order_status_constraint

Revision ID: pg_standalone_002
Revises: pg_standalone_001
Create Date: 2026-04-22

Adds missing indexes and order status CHECK constraint:
- idx_stockout_date: StockOut.stockout_date
- idx_purchase_order_created_by: PurchaseOrder.created_by
- order_status_check: Order.status CHECK constraint
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'pg_standalone_002'
down_revision = 'pg_standalone_001'
branch_labels = None
depends_on = None


def upgrade():
    # Index: stockout_date (frequent sort/filter field)
    op.create_index('idx_stockout_date', 'stock_out', ['stockout_date'])

    # Index: purchase_order.created_by (filter by creator)
    op.create_index('idx_purchase_order_created_by', 'purchase_order', ['created_by'])

    # CHECK constraint: order.status must be one of valid values
    # Note: Existing data must already conform to these values.
    # If any rows have invalid status, fix them before running this migration.
    op.execute(
        "ALTER TABLE \"order\" ADD CONSTRAINT order_status_check "
        "CHECK (\"status\" IN ('待备货', '部分备货', '已备货', '待出货', '已出货', '已完成', '已取消'))"
    )


def downgrade():
    op.drop_constraint('order_status_check', 'order', type_='check')
    op.drop_index('idx_purchase_order_created_by', table_name='purchase_order')
    op.drop_index('idx_stockout_date', table_name='stock_out')
