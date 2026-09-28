"""添加设备FCM令牌表

Revision ID: add_device_token
Revises: pg_standalone_009
Create Date: 2026-05-10
"""
import sqlalchemy as sa
from alembic import op

from migrations._legacy_base_guard import (
    base_schema_absent,
    create_index_if_columns_exist,
)

revision = 'add_device_token'
down_revision = 'pg_standalone_009'
branch_labels = None
depends_on = None

def upgrade():
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    op.create_table(
        'device_token',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('token', sa.String(255), unique=True, nullable=False, comment='FCM注册令牌'),
        sa.Column('platform', sa.String(20), server_default='android', comment='平台'),
        sa.Column('is_active', sa.Boolean(), server_default='true', comment='是否活跃'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )
    create_index_if_columns_exist('ix_device_token_user_active', 'device_token', ['user_id', 'is_active'])

def downgrade():
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    op.drop_table('device_token')
