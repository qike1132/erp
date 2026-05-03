"""add batch_no to order table

Revision ID: add_batch_no_order
Revises:
Create Date: 2026-04-20
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = 'add_batch_no_to_order'
down_revision = 'add_customer_code_to_customer'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('order', sa.Column('batch_no', sa.String(100), nullable=True, comment='批次号'))


def downgrade() -> None:
    op.drop_column('order', 'batch_no')
