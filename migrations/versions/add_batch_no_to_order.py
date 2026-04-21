"""add batch_no to order table

Revision ID: add_batch_no_order
Revises:
Create Date: 2026-04-20
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = 'add_batch_no_order'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('order', sa.Column('batch_no', sa.String(100), nullable=True, comment='批次号'))


def downgrade() -> None:
    op.drop_column('order', 'batch_no')
