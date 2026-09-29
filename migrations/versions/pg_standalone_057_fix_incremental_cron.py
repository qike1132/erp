"""纠正「自定义增量备份」的时刻：避免与 02:00 全量撞车

背景（承接 056）
----------------
056 已经把被删的 3 条例行调度补回，但它纠正增量时刻的那条 UPDATE 是按
**name** 匹配的（`WHERE name = '每日增量备份'`）—— 目的是不覆盖运维自己改过的
配置。生产实测该行已被**改名**为「自定义增量备份」，于是 UPDATE 未命中，
时刻仍是 `0 2 * * *`，与每日全量在同一分钟触发（IO 争用，且两者各自持锁不互斥）。

name 是用户可改的字段，不适合做迁移的匹配键；**task_type 才是稳定的**。
本迁移按 `task_type = 'incremental'` 匹配，并保留 `cron_expr = '0 2 * * *'`
这一取值守卫 —— 只纠正「与全量撞在同一分钟」的那些行，不动别处。

为何不直接改 056：它已应用到生产（`alembic_version` 已记录），迁移一经执行
就应保持与当时实际执行的语义一致；纠正动作另起一支，历史才读得懂。

Revision ID: pg_standalone_057_fix_incremental_cron
Revises: pg_standalone_056_restore_backup_schedules
Create Date: 2026-09-29
"""
from alembic import op

revision = 'pg_standalone_057_fix_incremental_cron'
down_revision = 'pg_standalone_056_restore_backup_schedules'
branch_labels = None
depends_on = None

_TASK_TYPE = 'incremental'
# 与每日全量 (0 2 * * *) 同分钟 —— 本迁移要消除的正是这个取值
_COLLIDING_CRON = '0 2 * * *'
# 036 种子的原作息
_EXPECTED_CRON = '0 6,10,14,18,22 * * *'


def upgrade() -> None:
    # 按 task_type 而非 name 匹配（name 可被用户改名，见模块 docstring）；
    # 取值守卫保证只动「与全量撞车」的行
    op.execute(
        "UPDATE backup_schedule "
        f"SET cron_expr = '{_EXPECTED_CRON}' "
        f"WHERE task_type = '{_TASK_TYPE}' AND cron_expr = '{_COLLIDING_CRON}'"
    )


def downgrade() -> None:
    """仅回退本迁移写入的值：任务在别处被再次调整过就不动它。"""
    op.execute(
        "UPDATE backup_schedule "
        f"SET cron_expr = '{_COLLIDING_CRON}' "
        f"WHERE task_type = '{_TASK_TYPE}' AND cron_expr = '{_EXPECTED_CRON}'"
    )
