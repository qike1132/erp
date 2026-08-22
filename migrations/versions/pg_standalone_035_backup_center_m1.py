"""备份中心 M1:backup_record 演进加列 + backup_schedule / backup_settings 新表

M1 备份任务化配套:
- backup_record 加列:manifest_summary(jsonb 摘要)、schedule_id(调度任务关联)、encrypted(加密标志)
- 新表 backup_schedule:定时备份任务配置(替代 ARQ 硬编码 cron,供 scheduler_poller 调度)
- 新表 backup_settings:备份存储路径与保留策略(单行,支持前端自定义路径)

Revision ID: pg_standalone_035_backup_center_m1
Revises: pg_standalone_034_numbering_counter
Create Date: 2026-08-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = 'pg_standalone_035_backup_center_m1'
down_revision = 'pg_standalone_034_numbering_counter'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- backup_record 演进加列 ----
    op.add_column('backup_record', sa.Column('manifest_summary', JSONB(), nullable=True, comment='manifest 摘要(行数/SHA-256 指纹/schema 快照)'))
    op.add_column('backup_record', sa.Column('schedule_id', sa.Integer(), nullable=True, comment='关联 backup_schedule 任务ID(手动触发为 NULL)'))
    op.add_column('backup_record', sa.Column('encrypted', sa.Boolean(), nullable=True, server_default=sa.false(), comment='备份文件是否加密'))
    op.create_index('idx_backup_record_schedule_id', 'backup_record', ['schedule_id'], unique=False)

    # ---- backup_schedule 新表 ----
    op.create_table(
        'backup_schedule',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(length=100), nullable=False, comment='任务名称'),
        sa.Column('task_type', sa.String(length=20), nullable=False, server_default='incremental', comment='任务类型: full/incremental'),
        sa.Column('cron_expr', sa.String(length=100), nullable=False, comment='cron 表达式(如 0 2 * * * 或 0 6,10,14,18,22 * * *)'),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true(), comment='是否启用'),
        sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True, comment='上次执行时间'),
        sa.Column('last_status', sa.String(length=20), nullable=True, comment='上次执行结果: success/failed/running'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), comment='更新时间'),
    )
    op.create_index('idx_backup_schedule_enabled', 'backup_schedule', ['enabled'], unique=False)

    # ---- backup_settings 新表(单行) ----
    op.create_table(
        'backup_settings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('backup_dir', sa.String(length=500), nullable=False, comment='备份存储路径'),
        sa.Column('retention_days', sa.Integer(), nullable=False, server_default='30', comment='保留天数'),
        sa.Column('max_count', sa.Integer(), nullable=False, server_default='50', comment='最大备份数量'),
        sa.Column('encryption_mode', sa.String(length=20), nullable=False, server_default='env', comment='加密模式: off/password/key/env'),
        sa.Column('updated_by', sa.String(length=100), nullable=True, comment='最后更新者用户名'),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), comment='更新时间'),
    )

    # 种子数据:默认路径(与 _constants.BACKUP_DIR 一致:backups/server 相对项目根)
    op.execute(
        "INSERT INTO backup_settings (id, backup_dir, retention_days, max_count, encryption_mode) "
        "VALUES (1, 'backups/server', 30, 50, 'env') "
        "ON CONFLICT (id) DO NOTHING"
    )


def downgrade() -> None:
    op.drop_table('backup_settings')
    op.drop_table('backup_schedule')
    op.drop_index('idx_backup_record_schedule_id', table_name='backup_record')
    op.drop_column('backup_record', 'encrypted')
    op.drop_column('backup_record', 'schedule_id')
    op.drop_column('backup_record', 'manifest_summary')
