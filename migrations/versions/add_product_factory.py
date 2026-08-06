"""添加 Product.factory 所属工厂字段

Revision ID: add_product_factory
Revises:
Create Date: 2026-08-04
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'add_product_factory'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('product', sa.Column('factory', sa.String(length=50), nullable=True))


def downgrade():
    op.drop_column('product', 'factory')
