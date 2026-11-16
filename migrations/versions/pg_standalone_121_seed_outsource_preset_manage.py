"""补齐工序预设权限点：outsource_preset_manage（2026-11-16 上线前审计 A-22）

背景：工序预设的增删改原先只认 `outsource_manage`，而 `scripts/add_outsource_nav.py`
历史上把 `outsource_manage` 授给了 `beile_order_view` / `order_manage` /
`stockin_manage` 的持有者 —— 贝乐（只需收货）因此能删工序预设，前端只是按用户名
把 Tab 藏起来，直调 API 即可绕过。

本次把预设写接口收窄到新码 `outsource_preset_manage`（见
`api/v1/endpoints/outsource.py` 的 PERM_PRESET_MANAGE）。但**只登记在 seed 脚本里不够**：
`User.has_permission` 只查库里的 permission 行，存量库没有这一行 = 除 `is_super` 外
无人能被授权（评审 ocr-s3b4-1）。故用这条纯数据迁移把行补进存量库。

**刻意不做「按 outsource_manage 回填授权」**：那会把贝乐重新变成预设维护者，
等于把本次要修的缺陷原样复活。上线后由 owner 在 /user 里显式勾给实际维护人；
超管的 `has_permission` 恒真，因此维护功能不会中断。

幂等：INSERT 带 NOT EXISTS 守卫；downgrade 仅在该码没有任何用户授权时删除。

Revision ID: pg_standalone_121_seed_outsource_preset_manage
Revises: pg_standalone_120_add_order_create_attempt
Create Date: 2026-11-16
"""
from alembic import op

revision = 'pg_standalone_121_seed_outsource_preset_manage'
down_revision = 'pg_standalone_120_add_order_create_attempt'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 顶层权限行（不挂 outsource_manage 之下）：子行会被父码无条件继承放行，
    # 那样职责分离就白做了 —— 与 scripts/seed_nav.py 的登记口径一致。
    op.execute(
        """
        INSERT INTO permission
            (name, code, parent_id, section, section_name, sort_order, is_nav, updated_at)
        SELECT '湖北外发（工序预设维护）', 'outsource_preset_manage',
               NULL, NULL, NULL, 0, false, now()
        WHERE NOT EXISTS (
            SELECT 1 FROM permission p2 WHERE p2.code = 'outsource_preset_manage'
        )
        """
    )


def downgrade() -> None:
    # 只在没有任何用户被授予时删除，避免降级把在用的授权打成孤儿。
    op.execute(
        """
        DELETE FROM permission
        WHERE code = 'outsource_preset_manage'
          AND NOT EXISTS (
              SELECT 1 FROM user_permission up
              WHERE up.permission_id = permission.id
          )
        """
    )
