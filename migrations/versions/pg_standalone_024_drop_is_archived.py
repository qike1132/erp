"""drop is_archived column from customer_sampling_project

Revision ID: pg_standalone_024_drop_is_archived
Revises: pg_standalone_023_add_status
Create Date: 2026-08-09
"""

from alembic import op
import sqlalchemy as sa

revision = 'pg_standalone_024_drop_is_archived'
down_revision = 'pg_standalone_023_add_status'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column('customer_sampling_project', 'is_archived')


def downgrade():
    op.add_column(
        'customer_sampling_project',
        sa.Column('is_archived', sa.Boolean(), nullable=False, server_default=sa.text('false'), comment='是否已归档'),
    )
    # 从 status 恢复数据
    op.execute("UPDATE customer_sampling_project SET is_archived = true WHERE status != 'in_progress'")
