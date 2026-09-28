"""
添加客户编码字段到客户表
"""
import sqlalchemy as sa
from alembic import op

from migrations._legacy_base_guard import (
    base_schema_absent,
    create_index_if_columns_exist,
)

revision = 'add_customer_code_to_customer'
down_revision = 'add_customer_to_purchase_order'
branch_labels = None
depends_on = None

def upgrade():
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    op.add_column('customer', sa.Column('customer_code', sa.String(50), nullable=True, comment='客户编码'))
    create_index_if_columns_exist('ix_customer_customer_code', 'customer', ['customer_code'], unique=False)

def downgrade():
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    op.drop_index('ix_customer_customer_code', 'customer')
    op.drop_column('customer', 'customer_code')
