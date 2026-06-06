"""添加备份记录表

Revision ID: add_backup_record
Revises: pg_standalone_011
Create Date: 2026-05-10
"""
import sqlalchemy as sa
from alembic import op

revision = 'add_backup_record'
down_revision = 'pg_standalone_011'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'backup_record',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('type', sa.String(20), nullable=False, comment='备份类型: full/incremental/restore'),
        sa.Column('trigger_type', sa.String(20), nullable=False, server_default='manual', comment='触发方式: manual/auto'),
        sa.Column('filename', sa.String(255), comment='备份文件名'),
        sa.Column('size', sa.BigInteger(), comment='文件大小(字节)'),
        sa.Column('table_count', sa.Integer(), comment='表数量'),
        sa.Column('total_rows', sa.BigInteger(), comment='总行数'),
        sa.Column('operator', sa.String(100), comment='操作者用户名'),
        sa.Column('remark', sa.Text(), comment='备注'),
        sa.Column('status', sa.String(20), nullable=False, server_default='running', comment='状态: success/failed/running'),
        sa.Column('error_message', sa.Text(), comment='错误信息'),
        sa.Column('duration_seconds', sa.Float(), comment='耗时(秒)'),
        sa.Column('ip_address', sa.String(45), comment='操作者IP地址'),
        sa.Column('user_agent', sa.Text(), comment='浏览器UA'),
        sa.Column('parent_record_id', sa.Integer(), comment='父备份记录ID(增量备份指向全量备份)'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), comment='更新时间'),
    )
    op.create_index('idx_backup_record_type', 'backup_record', ['type'])
    op.create_index('idx_backup_record_status', 'backup_record', ['status'])
    op.create_index('idx_backup_record_created_at', 'backup_record', ['created_at'])
    op.create_index('idx_backup_record_trigger_type', 'backup_record', ['trigger_type'])


def downgrade():
    op.drop_table('backup_record')
