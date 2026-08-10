"""add is_archived to customer_sampling_project

Revision ID: pg_standalone_022_add_is_archived
Revises: pg_standalone_021_remove_part_name_unique
Create Date: 2026-08-09

新增字段:
- customer_sampling_project.is_archived  归档标记（默认 false，表示打样中）
"""

from alembic import op
import sqlalchemy as sa

revision = 'pg_standalone_022_add_is_archived'
down_revision = 'pg_standalone_021_remove_part_name_unique'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'customer_sampling_project',
        sa.Column('is_archived', sa.Boolean(), nullable=False, server_default=sa.text('false'), comment='是否已归档'),
    )


def downgrade():
    op.drop_column('customer_sampling_project', 'is_archived')
