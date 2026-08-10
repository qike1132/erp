"""add status column to customer_sampling_project

Revision ID: pg_standalone_023_add_status
Revises: pg_standalone_022_add_is_archived
Create Date: 2026-08-09

新增字段:
- customer_sampling_project.status  状态枚举（in_progress/completed/cancelled，默认 in_progress）
- 从 is_archived 迁移数据：is_archived=true → status='completed'，false → status='in_progress'
- 保留 is_archived 列（后续迁移 024 删除）
"""

from alembic import op
import sqlalchemy as sa

revision = 'pg_standalone_023_add_status'
down_revision = 'pg_standalone_022_add_is_archived'
branch_labels = None
depends_on = None


def upgrade():
    # 1. 新增 status 列
    op.add_column(
        'customer_sampling_project',
        sa.Column('status', sa.String(20), nullable=False, server_default=sa.text("'in_progress'"), comment='状态：in_progress/completed/cancelled'),
    )

    # 2. 数据迁移：is_archived=true → completed
    op.execute("UPDATE customer_sampling_project SET status = 'completed' WHERE is_archived = true")

    # 3. 添加 CHECK 约束
    op.execute("ALTER TABLE customer_sampling_project ADD CONSTRAINT ck_csp_status_valid CHECK (status IN ('in_progress', 'completed', 'cancelled'))")


def downgrade():
    op.drop_constraint('ck_csp_status_valid', 'customer_sampling_project', type_='check')
    op.drop_column('customer_sampling_project', 'status')
