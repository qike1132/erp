"""add purchase_plan composite indexes and stock_out.returned_quantity

Revision ID: add_pp_composite_idx
Revises:
Create Date: 2026-05-05
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_pp_composite_idx'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index('idx_ppl_month_customer', 'purchase_plans', ['plan_month', 'customer_id'])
    op.create_index('idx_ppl_customer_name', 'purchase_plans', ['customer_name'])
    op.create_index('idx_ppd_product_name', 'purchase_plan_details', ['product_name'])


def downgrade() -> None:
    op.drop_index('idx_ppd_product_name', table_name='purchase_plan_details')
    op.drop_index('idx_ppl_customer_name', table_name='purchase_plans')
    op.drop_index('idx_ppl_month_customer', table_name='purchase_plans')
