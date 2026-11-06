"""BOM 三表新增「产品部位」列

Revision ID: pg_standalone_110_add_part_name_to_bom_tables
Revises: pg_standalone_109_add_user_token_version
Create Date: 2026-11-06

给 product_fabric / product_material / product_accessory 同时新增
``part_name VARCHAR(100) NULL``（产品部位，用户自由输入）。

仅结构变更，不夹带业务逻辑；三表同名列由 BOM 保存/复制服务统一读写。
"""
import sqlalchemy as sa
from alembic import op

revision = 'pg_standalone_110_add_part_name_to_bom_tables'
down_revision = 'pg_standalone_109_add_user_token_version'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'product_fabric',
        sa.Column('part_name', sa.String(length=100), nullable=True),
        if_not_exists=True,
    )
    op.execute("COMMENT ON COLUMN product_fabric.part_name IS '产品部位'")

    op.add_column(
        'product_material',
        sa.Column('part_name', sa.String(length=100), nullable=True),
        if_not_exists=True,
    )
    op.execute("COMMENT ON COLUMN product_material.part_name IS '产品部位'")

    op.add_column(
        'product_accessory',
        sa.Column('part_name', sa.String(length=100), nullable=True),
        if_not_exists=True,
    )
    op.execute("COMMENT ON COLUMN product_accessory.part_name IS '产品部位'")


def downgrade() -> None:
    op.drop_column('product_accessory', 'part_name')
    op.drop_column('product_material', 'part_name')
    op.drop_column('product_fabric', 'part_name')
