"""
添加客户字段到采购订单表
"""
import sqlalchemy as sa
from alembic import op

from migrations._legacy_base_guard import base_schema_absent

revision = 'add_customer_to_purchase_order'
down_revision = 'add_production_plan'
branch_labels = None
depends_on = None

def upgrade():
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    op.add_column('purchase_order', sa.Column('customer_id', sa.Integer(), nullable=True, comment='客户ID'))
    op.add_column('purchase_order', sa.Column('customer_name', sa.String(100), nullable=True, comment='客户名称(冗余)'))
    op.add_column('purchase_order', sa.Column('customer_code', sa.String(50), nullable=True, comment='客户编码'))
    op.create_foreign_key('fk_purchase_order_customer', 'purchase_order', 'customer', ['customer_id'], ['id'])

def downgrade():
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    op.drop_constraint('fk_purchase_order_customer', 'purchase_order', type_='foreignkey')
    op.drop_column('purchase_order', 'customer_code')
    op.drop_column('purchase_order', 'customer_name')
    op.drop_column('purchase_order', 'customer_id')
