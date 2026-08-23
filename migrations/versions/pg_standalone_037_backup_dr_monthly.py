"""备份中心 M6:灾备恢复演练月度例行化种子

P1-4(2026-08-23 对标审核整改):把 disaster_recovery_test_task 纳入 backup_schedule
调度——每月 1 日 03:30 自动演练"备份可恢复"，让备份可信度从假设变成持续验证
的事实（对标 DBackup 的定时完整性重扫）。

Revision ID: pg_standalone_037_backup_dr_monthly
Revises: pg_standalone_036_backup_center_m2
Create Date: 2026-08-23
"""
from alembic import op

revision = 'pg_standalone_037_backup_dr_monthly'
down_revision = 'pg_standalone_036_backup_center_m2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 幂等种子：不重复插入同名调度
    op.execute(
        "INSERT INTO backup_schedule (name, task_type, cron_expr, enabled) "
        "SELECT '月度灾备恢复演练', 'disaster_recovery_test', '30 3 1 * *', TRUE "
        "WHERE NOT EXISTS (SELECT 1 FROM backup_schedule WHERE name = '月度灾备恢复演练')"
    )


def downgrade() -> None:
    op.execute("DELETE FROM backup_schedule WHERE name = '月度灾备恢复演练'")
