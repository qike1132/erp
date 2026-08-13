"""add completed_at to customer_sampling_project - 打样模块已完成项目查询

为板房打样（/pattern-room）模块的已完成项目查询功能，在
customer_sampling_project 表新增 completed_at 字段（标记完成时间），
并创建倒序索引以支持按完成时间排序查询。

执行方式：标准 DDL 一次性迁移。
回滚：downgrade 删除索引与列。

Revision ID: pg_standalone_032_add_completed_at
Revises: pg_standalone_031_pattern_maker
Create Date: 2026-08-13
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'pg_standalone_032_add_completed_at'
down_revision = 'pg_standalone_031_pattern_maker'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'customer_sampling_project',
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True, comment='完成时间'),
    )
    op.create_index(
        'idx_csp_completed_at', 'customer_sampling_project', ['completed_at'],
    )


def downgrade():
    op.drop_index('idx_csp_completed_at', table_name='customer_sampling_project')
    op.drop_column('customer_sampling_project', 'completed_at')
