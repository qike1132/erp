"""add missing indexes for customer_sampling models

Revision ID: pg_standalone_025_add_cs_indexes
Revises: pg_standalone_024_drop_is_archived
Create Date: 2026-08-10

补建 ORM 模型中已声明但数据库中尚未创建的索引：
- customer_sampling_fabric_version: idx_csfv_project_version
- customer_sampling_change_log: idx_cscl_created_at
"""
import sqlalchemy as sa
from alembic import op

from migrations._legacy_base_guard import create_index_if_columns_exist

revision = 'pg_standalone_025_add_cs_indexes'
down_revision = 'pg_standalone_024_drop_is_archived'
branch_labels = None
depends_on = None

def upgrade():
    # 1. 版本快照表：项目+版本查询索引
    create_index_if_columns_exist(
        'idx_csfv_project_version',
        'customer_sampling_fabric_version',
        ['project_id', 'version_no'],
    )

    # 2. 变更日志表：按时间倒序索引
    create_index_if_columns_exist(
        'idx_cscl_created_at',
        'customer_sampling_change_log',
        [sa.text('created_at DESC')],
    )

def downgrade():
    op.drop_index('idx_cscl_created_at', table_name='customer_sampling_change_log', if_exists=True)
    op.drop_index('idx_csfv_project_version', table_name='customer_sampling_fabric_version', if_exists=True)
