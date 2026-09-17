"""补齐湖北订单导出/打印权限点：beile_order_export / beile_order_print

背景：前端 useBeileOrders.ts 以这两个权限码控制湖北订单页的导出/打印按钮显隐，
但生产库从未种入，导致所有非超管用户（含「贝乐」）的导出/打印永远隐藏。

方案（与 pg_standalone_043 同类幂等处理）：
- 创建为 beile_order_view 的子权限（hubei 板块、非导航项）。
- 显式授予当前持有 beile_order_view 的用户（前端 /auth/me 只返回直接授权，
  子权限继承不会反映到前端 hasPermission，故必须显式回填）。

幂等：权限创建带 NOT EXISTS 守卫，授权回填带 ON CONFLICT DO NOTHING。

Revision ID: pg_standalone_044_seed_beile_export_print
Revises: pg_standalone_043_seed_missing_permissions
Create Date: 2026-09-15
"""
from alembic import op

revision = 'pg_standalone_044_seed_beile_export_print'
down_revision = 'pg_standalone_043_seed_missing_permissions'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. beile_order_export：湖北订单导出（beile_order_view 的子权限）
    op.execute(
        """
        INSERT INTO permission (name, code, parent_id, section, section_name, sort_order, is_nav, updated_at)
        SELECT '湖北订单（导出）', 'beile_order_export', id, section, section_name, sort_order + 1, false, now()
        FROM permission
        WHERE code = 'beile_order_view'
          AND NOT EXISTS (SELECT 1 FROM permission p2 WHERE p2.code = 'beile_order_export')
        """
    )

    # 2. beile_order_print：湖北订单打印（beile_order_view 的子权限）
    op.execute(
        """
        INSERT INTO permission (name, code, parent_id, section, section_name, sort_order, is_nav, updated_at)
        SELECT '湖北订单（打印）', 'beile_order_print', id, section, section_name, sort_order + 2, false, now()
        FROM permission
        WHERE code = 'beile_order_view'
          AND NOT EXISTS (SELECT 1 FROM permission p2 WHERE p2.code = 'beile_order_print')
        """
    )

    # 3. 显式授予持有 beile_order_view 的用户（当前仅「贝乐」）
    op.execute(
        """
        INSERT INTO user_permission (user_id, permission_id)
        SELECT up.user_id, p.id
        FROM user_permission up
        JOIN permission pv ON pv.id = up.permission_id AND pv.code = 'beile_order_view'
        JOIN permission p ON p.code IN ('beile_order_export', 'beile_order_print')
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    for code in ('beile_order_export', 'beile_order_print'):
        op.execute(
            f"""
            DELETE FROM user_permission
            WHERE permission_id IN (SELECT id FROM permission WHERE code = '{code}')
            """
        )
        op.execute(f"DELETE FROM permission WHERE code = '{code}'")
