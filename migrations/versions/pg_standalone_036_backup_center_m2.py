"""备份中心 M2:backup_schedule 种子数据(把 ARQ 硬编码 cron 迁入表)

M2 调度 DB 化:
- 将原 arq_app.cron_schedules 的 4 项备份定时迁入 backup_schedule 表:
  每日全量 02:00、每日增量 06/10/14/18/22、完整性巡检 03:00、清理 04:00
- 由 scheduler_poller 每 5 分钟扫描本表调度执行,迁移后定时行为与现状等价

Revision ID: pg_standalone_036_backup_center_m2
Revises: pg_standalone_035_backup_center_m1
Create Date: 2026-08-22
"""
from alembic import op

revision = 'pg_standalone_036_backup_center_m2'
down_revision = 'pg_standalone_035_backup_center_m1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 幂等种子:与 035 建表后首次迁移对齐,不重复插入同 cron 的行
    op.execute(
        "INSERT INTO backup_schedule (name, task_type, cron_expr, enabled) "
        "SELECT '每日全量备份', 'full', '0 2 * * *', TRUE "
        "WHERE NOT EXISTS (SELECT 1 FROM backup_schedule WHERE name = '每日全量备份')"
    )
    op.execute(
        "INSERT INTO backup_schedule (name, task_type, cron_expr, enabled) "
        "SELECT '每日增量备份', 'incremental', '0 6,10,14,18,22 * * *', TRUE "
        "WHERE NOT EXISTS (SELECT 1 FROM backup_schedule WHERE name = '每日增量备份')"
    )
    op.execute(
        "INSERT INTO backup_schedule (name, task_type, cron_expr, enabled) "
        "SELECT '备份完整性巡检', 'integrity_check', '0 3 * * *', TRUE "
        "WHERE NOT EXISTS (SELECT 1 FROM backup_schedule WHERE name = '备份完整性巡检')"
    )
    op.execute(
        "INSERT INTO backup_schedule (name, task_type, cron_expr, enabled) "
        "SELECT '备份清理', 'cleanup', '0 4 * * *', TRUE "
        "WHERE NOT EXISTS (SELECT 1 FROM backup_schedule WHERE name = '备份清理')"
    )


def downgrade() -> None:
    op.execute("DELETE FROM backup_schedule WHERE name IN ('每日全量备份','每日增量备份','备份完整性巡检','备份清理')")