"""补齐湖北订单确认权限点：beile_order_confirm

背景：湖北订单/备货确认接口原先挂载 beile_order_view，任何可查看
湖北订单的用户都能确认，缺少独立的确认权限点。

方案（与 pg_standalone_044 同类幂等处理）：
- 创建为 beile_order_view 的子权限（hubei 板块、非导航项）。
- 显式授予当前持有 beile_order_view 的用户（前端 /auth/me 只返回直接授权，
  子权限继承不会反映到前端 hasPermission，故必须显式回填），
  保证上线后现有用户确认按钮行为不变。

幂等：权限创建带 NOT EXISTS 守卫，授权回填带 ON CONFLICT DO NOTHING。

Revision ID: pg_standalone_048_seed_beile_confirm
Revises: add_outsource_shipment
Create Date: 2026-09-21
"""
from alembic import op

revision = 'pg_standalone_048_seed_beile_confirm'
down_revision = 'add_outsource_shipment'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # beile_order_confirm：湖北订单/备货确认（beile_order_view 的子权限）
    op.execute(
        """
        INSERT INTO permission (name, code, parent_id, section, section_name, sort_order, is_nav, updated_at)
        SELECT '湖北订单（确认）', 'beile_order_confirm', id, section, section_name, sort_order + 3, false, now()
        FROM permission
        WHERE code = 'beile_order_view'
          AND NOT EXISTS (SELECT 1 FROM permission p2 WHERE p2.code = 'beile_order_confirm')
        """
    )

    # 显式授予持有 beile_order_view 的用户（现有用户行为不变）
    op.execute(
        """
        INSERT INTO user_permission (user_id, permission_id)
        SELECT up.user_id, p.id
        FROM user_permission up
        JOIN permission pv ON pv.id = up.permission_id AND pv.code = 'beile_order_view'
        JOIN permission p ON p.code = 'beile_order_confirm'
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM user_permission
        WHERE permission_id IN (SELECT id FROM permission WHERE code = 'beile_order_confirm')
        """
    )
    op.execute("DELETE FROM permission WHERE code = 'beile_order_confirm'")
