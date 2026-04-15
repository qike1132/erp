"""
添加客户字段到采购订单表
"""
from alembic import op
import sqlalchemy as sa


revision = 'add_customer_to_purchase_order'
down_revision = '659467a97350_add_approval_system_and_order_lock_'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('purchase_order', sa.Column('customer_id', sa.Integer(), nullable=True, comment='客户ID'))
    op.add_column('purchase_order', sa.Column('customer_name', sa.String(100), nullable=True, comment='客户名称(冗余)'))
    op.add_column('purchase_order', sa.Column('customer_code', sa.String(50), nullable=True, comment='客户编码'))
    op.create_foreign_key('fk_purchase_order_customer', 'purchase_order', 'customer', ['customer_id'], ['id'])


def downgrade():
    op.drop_constraint('fk_purchase_order_customer', 'purchase_order', type_='foreignkey')
    op.drop_column('purchase_order', 'customer_code')
    op.drop_column('purchase_order', 'customer_name')
    op.drop_column('purchase_order', 'customer_id')
