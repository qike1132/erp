"""板房管理权限码迁移：pattern_room_manage -> customer_sampling_manage

完成 pg_standalone_019_customer_sampling 中「权限码迁移留待 T14」的遗留事项。

背景：
- 打样模块（customer_sampling / pattern_maker）接口与前端自 2026-08 起统一使用
  customer_sampling_manage 权限码（见 endpoints/customer_sampling.py:66）。
- 但权限目录数据迁移一直未执行：生产库 permission 表仍只有旧码 pattern_room_manage，
  且该码被授予了业务用户（如用户 001）。
- 后果：所有非超管用户调用板房写接口（如新增版师
  POST /api/v1/pattern-maker/pattern-makers）均被 403 Forbidden 拒绝。

方案：
- 原位 UPDATE 更名（保留 id=234），user_permission 授权随 id 自动迁移到新码，
  无需新增/删除行，无孤儿授权风险；导航元数据（名称/图标/链接/排序）保持不变。
- 迁移带幂等保护：新码已存在（如个别环境提前手工完成）时跳过。

Revision ID: pg_standalone_042_rename_pattern_room_permission
Revises: pg_standalone_041_web_vital
Create Date: 2026-09-15
"""
from alembic import op

revision = 'pg_standalone_042_rename_pattern_room_permission'
down_revision = 'pg_standalone_041_web_vital'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE permission
        SET code = 'customer_sampling_manage', updated_at = now()
        WHERE code = 'pattern_room_manage'
          AND NOT EXISTS (
              SELECT 1 FROM permission p2 WHERE p2.code = 'customer_sampling_manage'
          )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE permission
        SET code = 'pattern_room_manage', updated_at = now()
        WHERE code = 'customer_sampling_manage'
          AND NOT EXISTS (
              SELECT 1 FROM permission p2 WHERE p2.code = 'pattern_room_manage'
          )
        """
    )
