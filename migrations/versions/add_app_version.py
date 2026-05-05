"""添加 App版本管理表

Revision ID: add_app_version
Revises: add_production_plan
Create Date: 2026-05-05
"""
import sqlalchemy as sa
from alembic import op

revision = 'add_app_version'
down_revision = 'add_production_plan'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'app_version',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('platform', sa.String(20), nullable=False, server_default='android', comment='平台: android/ios'),
        sa.Column('version_code', sa.Integer(), nullable=False, index=True, comment='整数版本号（用于对比）'),
        sa.Column('version_name', sa.String(50), nullable=False, comment='显示版本号，如 1.0.1'),
        sa.Column('download_url', sa.String(500), nullable=False, comment='APK下载地址'),
        sa.Column('changelog', sa.Text(), nullable=True, comment='更新日志'),
        sa.Column('file_size', sa.Integer(), nullable=True, comment='文件大小（字节）'),
        sa.Column('md5_hash', sa.String(64), nullable=True, comment='MD5校验值'),
        sa.Column('force_update', sa.Boolean(), server_default='0', comment='是否强制更新'),
        sa.Column('is_active', sa.Boolean(), server_default='1', comment='是否当前有效版本'),
        sa.Column('pushed', sa.Boolean(), server_default='0', comment='是否已推送FCM通知'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), comment='创建时间'),
    )

    op.create_index('idx_app_version_platform_code', 'app_version', ['platform', 'version_code'])


def downgrade():
    op.drop_table('app_version')
