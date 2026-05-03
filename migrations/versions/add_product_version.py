"""添加 Product.version 乐观锁字段

Revision ID: add_product_version
Revises:
Create Date: 2026-04-12
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'add_product_version'
down_revision = 'add_product_price'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('product', sa.Column('version', sa.Integer(), nullable=False, server_default='0'))


def downgrade():
    op.drop_column('product', 'version')
