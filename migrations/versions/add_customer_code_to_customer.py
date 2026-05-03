"""
添加客户编码字段到客户表
"""
import sqlalchemy as sa
from alembic import op

revision = 'add_customer_code_to_customer'
down_revision = 'add_customer_to_purchase_order'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('customer', sa.Column('customer_code', sa.String(50), nullable=True, comment='客户编码'))
    op.create_index('ix_customer_customer_code', 'customer', ['customer_code'], unique=False)


def downgrade():
    op.drop_index('ix_customer_customer_code', 'customer')
    op.drop_column('customer', 'customer_code')
