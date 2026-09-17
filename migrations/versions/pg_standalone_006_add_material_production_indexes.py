"""pg_standalone_006_add_material_production_indexes

Revision ID: pg_standalone_006
Revises: pg_standalone_005
Create Date: 2026-05-05

为来料登记和每日生产记录添加性能索引，覆盖高频查询场景。
"""

from alembic import op

revision = 'pg_standalone_006'
down_revision = 'pg_standalone_005'
branch_labels = ()
depends_on = None


def upgrade() -> None:
    op.create_index('idx_material_reg_purchase_order', 'material_registration', ['purchase_order_id'])
    op.create_index('idx_material_reg_supplier', 'material_registration', ['supplier_id'])
    op.create_index('idx_material_reg_status', 'material_registration', ['status'])
    op.create_index('idx_material_reg_date', 'material_registration', ['registration_date'])
    op.create_index('idx_material_reg_status_date', 'material_registration', ['status', 'registration_date'])
    op.create_index('idx_dpr_product_id', 'daily_production_record', ['product_id'])


def downgrade() -> None:
    op.drop_index('idx_dpr_product_id', table_name='daily_production_record')
    op.drop_index('idx_material_reg_status_date', table_name='material_registration')
    op.drop_index('idx_material_reg_date', table_name='material_registration')
    op.drop_index('idx_material_reg_status', table_name='material_registration')
    op.drop_index('idx_material_reg_supplier', table_name='material_registration')
    op.drop_index('idx_material_reg_purchase_order', table_name='material_registration')
