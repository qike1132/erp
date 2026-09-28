"""pg_standalone_006_add_material_production_indexes

Revision ID: pg_standalone_006
Revises: pg_standalone_005
Create Date: 2026-05-05

为来料登记和每日生产记录添加性能索引，覆盖高频查询场景。
"""

from alembic import op

from migrations._legacy_base_guard import (
    base_schema_absent,
    create_index_if_columns_exist,
)

revision = 'pg_standalone_006'
down_revision = 'pg_standalone_005'
branch_labels = ()
depends_on = None

def upgrade() -> None:
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    create_index_if_columns_exist('idx_material_reg_purchase_order', 'material_registration', ['purchase_order_id'])
    create_index_if_columns_exist('idx_material_reg_supplier', 'material_registration', ['supplier_id'])
    create_index_if_columns_exist('idx_material_reg_status', 'material_registration', ['status'])
    create_index_if_columns_exist('idx_material_reg_date', 'material_registration', ['registration_date'])
    create_index_if_columns_exist('idx_material_reg_status_date', 'material_registration', ['status', 'registration_date'])
    create_index_if_columns_exist('idx_dpr_product_id', 'daily_production_record', ['product_id'])

def downgrade() -> None:
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    op.drop_index('idx_dpr_product_id', table_name='daily_production_record', if_exists=True)
    op.drop_index('idx_material_reg_status_date', table_name='material_registration', if_exists=True)
    op.drop_index('idx_material_reg_date', table_name='material_registration', if_exists=True)
    op.drop_index('idx_material_reg_status', table_name='material_registration', if_exists=True)
    op.drop_index('idx_material_reg_supplier', table_name='material_registration', if_exists=True)
    op.drop_index('idx_material_reg_purchase_order', table_name='material_registration', if_exists=True)
