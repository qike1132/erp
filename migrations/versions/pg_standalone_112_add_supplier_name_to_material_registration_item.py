"""来料登记明细新增「供应商」列

Revision ID: pg_standalone_112_add_supplier_name_to_material_registration_item
Revises: pg_standalone_111_add_part_name_to_purchase_order_item
Create Date: 2026-11-07

给 material_registration_item 新增 ``supplier_name VARCHAR(100) NULL``（明细级供应商）。
创建来料登记时从采购明细 / BOM 行带入，/material 按明细供应商分组；
旧登记保持 NULL，前端回退到登记级 supplier_name。

仅结构变更，不夹带业务逻辑。
"""
import sqlalchemy as sa
from alembic import op

revision = 'pg_standalone_112_add_supplier_name_to_material_registration_item'
down_revision = 'pg_standalone_111_add_part_name_to_purchase_order_item'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'material_registration_item',
        sa.Column('supplier_name', sa.String(length=100), nullable=True),
        if_not_exists=True,
    )
    op.execute(
        "COMMENT ON COLUMN material_registration_item.supplier_name IS '供应商名称(明细级)'"
    )


def downgrade() -> None:
    op.drop_column('material_registration_item', 'supplier_name')
