"""添加 Product.price 产品价格字段

Revision ID: add_product_price
Revises:
Create Date: 2026-04-14
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'add_product_price'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('product', sa.Column('price', sa.Numeric(10, 2), nullable=True, server_default='0'))


def downgrade():
    op.drop_column('product', 'price')
