"""remove part_name unique constraint and add fabric_color_no column

Revision ID: pg_standalone_021_remove_part_name_unique
Revises: pg_standalone_020_cs_changelog_set_null
Create Date: 2026-08-08

- 添加 fabric_color_no 字段到 customer_sampling_part 表
- 删除 uq_csp_part_name 唯一约束（project_id + part_name），支持同一部位下多个子项 T1/T2/T3
- 创建普通索引 idx_csp_part_name 用于按部位名称查询
"""
import sqlalchemy as sa
from alembic import op

from migrations._legacy_base_guard import create_index_if_columns_exist

revision = 'pg_standalone_021_remove_part_name_unique'
down_revision = 'pg_standalone_020_cs_changelog_set_null'
branch_labels = None
depends_on = None

def upgrade():
    # 添加 fabric_color_no 字段
    op.add_column('customer_sampling_part', sa.Column('fabric_color_no', sa.String(50), comment='色号'))

    # 删除唯一约束
    op.drop_constraint('uq_csp_part_name', 'customer_sampling_part', type_='unique')
    # 创建普通索引
    create_index_if_columns_exist('idx_csp_part_name', 'customer_sampling_part', ['project_id', 'part_name'])

def downgrade():
    # 删除普通索引
    op.drop_index('idx_csp_part_name', table_name='customer_sampling_part', if_exists=True)
    # 恢复唯一约束（注意：如果已有重复数据会失败）
    op.create_unique_constraint('uq_csp_part_name', 'customer_sampling_part', ['project_id', 'part_name'])

    # 删除 fabric_color_no 字段
    op.drop_column('customer_sampling_part', 'fabric_color_no')
