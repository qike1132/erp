"""添加国家表

Revision ID: add_country_table
Revises: add_device_token
Create Date: 2026-06-04
"""
import sqlalchemy as sa
from alembic import op

revision = 'add_country_table'
down_revision = 'add_device_token'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'country',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(100), unique=True, nullable=False, comment='国家名称'),
    )


def downgrade():
    op.drop_table('country')