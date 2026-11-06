"""采购明细新增「产品部位」列

Revision ID: pg_standalone_111_add_part_name_to_purchase_order_item
Revises: pg_standalone_110_add_part_name_to_bom_tables
Create Date: 2026-11-06

给 purchase_order_item 新增 ``part_name VARCHAR(100) NULL``（产品部位）。
生成采购明细时从 BOM 行带入；旧单保持 NULL，由工厂汇总按物料合并回退。

仅结构变更，不夹带业务逻辑。
"""
import sqlalchemy as sa
from alembic import op

revision = 'pg_standalone_111_add_part_name_to_purchase_order_item'
down_revision = 'pg_standalone_110_add_part_name_to_bom_tables'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'purchase_order_item',
        sa.Column('part_name', sa.String(length=100), nullable=True),
        if_not_exists=True,
    )
    op.execute("COMMENT ON COLUMN purchase_order_item.part_name IS '产品部位'")


def downgrade() -> None:
    op.drop_column('purchase_order_item', 'part_name')
