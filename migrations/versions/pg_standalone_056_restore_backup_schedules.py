"""备份调度修复：补回被删的例行任务 + 纠正增量时刻

背景（/backup 上线前审计）
--------------------------
生产库 `backup_schedule` 实测只剩 2 行，且增量被改成与全量同一时刻：

    每日全量备份      full                0 2 * * *            （正常）
    每日增量备份      incremental         0 2 * * *            （应为 0 6,10,14,18,22）
    备份完整性巡检    integrity_check                          —— 缺失
    备份清理          cleanup                                  —— 缺失
    月度灾备恢复演练  disaster_recovery_test                   —— 缺失

后果：没有任何自动的备份可用性校验（备份到底能不能还原，只能靠人想起来跑），
也没有月度灾备演练。删除路径只有 UI 的 `DELETE /backup/schedule/{id}`，仓库内
没有批量重置逻辑 —— 所以这是界面误删造成的漂移，不是 036/037 种子本身的问题
（036 建表即种了 4 条，037 补了月度演练）。

本迁移做两件事，都幂等：
1. 按 name 补回缺失的 3 条；
2. 把「每日增量备份」从漂移值 `0 2 * * *` 纠回 `0 6,10,14,18,22 * * *`，
   且**仅当它仍是那个漂移值时才改**，不覆盖运维另行设定的时刻。

**cleanup 故意以 enabled=FALSE 插入**：它会按保留策略真删备份文件，上线阶段
先让人确认保留天数与磁盘策略，再在界面里显式打开（服务内部另有「至少留一个
可还原备份」的兜底）。integrity_check 只读，演练在隔离环境跑，故默认开启。

**已知局限（由 057 补上）**：下面纠正增量时刻的 UPDATE 按 **name** 匹配，
而 name 是用户可改字段 —— 生产那行已被改名为「自定义增量备份」，本迁移因此
未命中。057 改用稳定的 `task_type` 匹配。不要回头修改本文件：它已应用到生产，
须与实际执行的语义保持一致。

Revision ID: pg_standalone_056_restore_backup_schedules
Revises: pg_standalone_055_remove_custom_order_country
Create Date: 2026-09-28
"""
from alembic import op

revision = 'pg_standalone_056_restore_backup_schedules'
down_revision = 'pg_standalone_055_remove_custom_order_country'
branch_labels = None
depends_on = None

# (name, task_type, cron_expr, enabled) —— 与 036/037 的种子保持一致，只有 cleanup 例外
_MISSING_SEEDS = (
    ('备份完整性巡检', 'integrity_check', '0 3 * * *', 'TRUE'),
    ('备份清理', 'cleanup', '0 4 * * *', 'FALSE'),
    ('月度灾备恢复演练', 'disaster_recovery_test', '30 3 1 * *', 'TRUE'),
)

_INCREMENTAL_NAME = '每日增量备份'
_INCREMENTAL_DRIFTED = '0 2 * * *'
_INCREMENTAL_EXPECTED = '0 6,10,14,18,22 * * *'


def upgrade() -> None:
    for name, task_type, cron_expr, enabled in _MISSING_SEEDS:
        # 幂等：同名存在即跳过，绝不覆盖运维改过的行
        op.execute(
            "INSERT INTO backup_schedule (name, task_type, cron_expr, enabled) "
            f"SELECT '{name}', '{task_type}', '{cron_expr}', {enabled} "
            f"WHERE NOT EXISTS (SELECT 1 FROM backup_schedule WHERE name = '{name}')"
        )

    # 只在「仍是我们诊断到的那个漂移值」时纠正，避免覆盖有意的调整
    op.execute(
        "UPDATE backup_schedule "
        f"SET cron_expr = '{_INCREMENTAL_EXPECTED}' "
        f"WHERE name = '{_INCREMENTAL_NAME}' AND cron_expr = '{_INCREMENTAL_DRIFTED}'"
    )


def downgrade() -> None:
    """回滚只撤销本迁移**新增**的行与那次时刻纠正，不动 036/037 原有数据。

    增量时刻按同样的「仅当仍是本迁移写入值」条件回退，避免误伤。
    """
    op.execute(
        "UPDATE backup_schedule "
        f"SET cron_expr = '{_INCREMENTAL_DRIFTED}' "
        f"WHERE name = '{_INCREMENTAL_NAME}' AND cron_expr = '{_INCREMENTAL_EXPECTED}'"
    )
    for name, _task_type, _cron_expr, _enabled in _MISSING_SEEDS:
        op.execute(f"DELETE FROM backup_schedule WHERE name = '{name}'")
