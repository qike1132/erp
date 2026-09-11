"""BOM 配置·角色字段：product 表增加 default_bom_label

支持产品级默认 BOM 的自定义名称（"默认BOM"标签可双击改名并持久化）。
NULL 表示使用默认展示名"默认BOM"。

Revision ID: pg_standalone_039_product_default_bom_label
Revises: pg_standalone_038_product_role
Create Date: 2026-09-11
"""
from alembic import op

revision = 'pg_standalone_039_product_default_bom_label'
down_revision = 'pg_standalone_038_product_role'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE product ADD COLUMN default_bom_label VARCHAR(50);")
    op.execute("COMMENT ON COLUMN product.default_bom_label IS '默认BOM自定义名称(NULL=显示默认BOM)';")


def downgrade() -> None:
    op.execute("ALTER TABLE product DROP COLUMN default_bom_label;")
