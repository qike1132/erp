"""add purchase_plan composite indexes and stock_out.returned_quantity

Revision ID: add_pp_composite_idx
Revises:
Create Date: 2026-05-05
"""
from alembic import op

from migrations._legacy_base_guard import (
    base_schema_absent,
    create_index_if_columns_exist,
)

revision = 'add_pp_composite_idx'
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    create_index_if_columns_exist('idx_ppl_month_customer', 'purchase_plans', ['plan_month', 'customer_id'])
    create_index_if_columns_exist('idx_ppl_customer_name', 'purchase_plans', ['customer_name'])
    create_index_if_columns_exist('idx_ppd_product_name', 'purchase_plan_details', ['product_name'])

def downgrade() -> None:
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    op.drop_index('idx_ppd_product_name', table_name='purchase_plan_details', if_exists=True)
    op.drop_index('idx_ppl_customer_name', table_name='purchase_plans', if_exists=True)
    op.drop_index('idx_ppl_month_customer', table_name='purchase_plans', if_exists=True)
