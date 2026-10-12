"""删除增量备份残留：backup_schedule 的 incremental 行 + backup_record 的增量历史

背景：/backup 收敛为全量-only（见 docs/superpowers/specs/2026-10-12-full-only-backup-design.md）。
036/056 曾种下 incremental 调度行，本迁移幂等删除；历史增量记录一并清理。
DELETE 不触发 destructive DDL 扫描。

Revision ID: pg_standalone_094_drop_incremental_backup
Revises: pg_standalone_093_backup_child_permissions
"""
from alembic import op

revision = 'pg_standalone_094_drop_incremental_backup'
down_revision = 'pg_standalone_093_backup_child_permissions'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DELETE FROM backup_schedule WHERE task_type = 'incremental'")
    op.execute("DELETE FROM backup_record WHERE type = 'incremental'")


def downgrade() -> None:
    # 数据删除不可逆；回滚仅恢复调度行（enabled=FALSE，与 056 口径一致）
    op.execute(
        "INSERT INTO backup_schedule (name, task_type, cron_expr, enabled) "
        "SELECT '每日增量备份', 'incremental', '0 6,10,14,18,22 * * *', FALSE "
        "WHERE NOT EXISTS (SELECT 1 FROM backup_schedule WHERE task_type = 'incremental')"
    )
