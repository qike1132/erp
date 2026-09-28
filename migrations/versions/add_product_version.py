"""添加 Product.version 乐观锁字段

Revision ID: add_product_version
Revises:
Create Date: 2026-04-12
"""
import sqlalchemy as sa
from alembic import op

from migrations._legacy_base_guard import base_schema_absent

# revision identifiers, used by Alembic.
revision = 'add_product_version'
down_revision = 'add_product_price'
branch_labels = None
depends_on = None

def upgrade():
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    op.add_column('product', sa.Column('version', sa.Integer(), nullable=False, server_default='0'))

def downgrade():
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    op.drop_column('product', 'version')
