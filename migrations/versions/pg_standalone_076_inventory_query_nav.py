"""「库存查询」独立路由导航项（订单查询分区）

背景：/stock 原以 tab 承载「库存查询（生产 − 出货 快照）」与「库存汇总」。
2026-10-07 业务拍板：库存查询独立成路由 /inventory-query，并在侧边栏
「订单查询」分区（section=data）单列导航项，插在「订单列表」(sort_order=0)
与「订单流水」(2) 之间。

- 新权限码 ``stock.inventory_query``（url=stock.inventory_query，is_nav=True）：
  url 经 core/nav_context.py 的 PERMISSION_URL_MAP 映射到前端路由 /inventory-query。
- 授权复制：持有 ``stock_view``（订单列表，即原 /stock 入口）的用户自动获得
  本导航项，避免上线后普通用户的库存入口消失；后续可在 /user 页单独勾选。
- API 授权不变：GET /stock/inventory-snapshot 仍要求 stock_view | stockin_manage，
  与导航可见性解耦（fail-closed 在接口层）。

幂等：按 code 唯一约束 NOT EXISTS 守卫 + user_permission 主键 ON CONFLICT，
重复执行安全。

Revision ID: pg_standalone_076_inventory_query_nav
Revises: pg_standalone_075_order_row_action_permissions
Create Date: 2026-10-07
"""
from alembic import op

revision = 'pg_standalone_076_inventory_query_nav'
down_revision = 'pg_standalone_075_order_row_action_permissions'
branch_labels = None
depends_on = None

_CODE = 'stock.inventory_query'


def upgrade() -> None:
    # 导航项：icon 沿用本分区「订单列表」的 FontAwesome 约定；sort_order=1 插在中间
    op.execute(
        "INSERT INTO permission (code, name, icon, url, section, section_name, sort_order, is_nav, updated_at) "
        "SELECT '" + _CODE + "', '库存查询', 'fa-boxes-stacked', '" + _CODE + "', "
        "'data', '订单查询', 1, True, now() "
        "WHERE NOT EXISTS (SELECT 1 FROM permission WHERE code = '" + _CODE + "')"
    )  # nosec B608 — 常量表插值，无外部输入
    # 授权复制：stock_view 持有者同步获得新导航项（主键 ON CONFLICT 保证幂等）
    op.execute(
        "INSERT INTO user_permission (user_id, permission_id) "
        "SELECT up.user_id, p2.id FROM user_permission up "
        "JOIN permission p ON p.id = up.permission_id AND p.code = 'stock_view' "
        "JOIN permission p2 ON p2.code = '" + _CODE + "' "
        "ON CONFLICT DO NOTHING"
    )  # nosec B608 — 常量表插值，无外部输入


def downgrade() -> None:
    # user_permission 外键无级联，先删授权行再删权限点（075 同款）
    op.execute(
        "DELETE FROM user_permission WHERE permission_id IN "
        "(SELECT id FROM permission WHERE code = '" + _CODE + "')"
    )  # nosec B608 — 常量表插值，无外部输入
    op.execute(
        "DELETE FROM permission WHERE code = '" + _CODE + "'"
    )  # nosec B608 — 常量表插值，无外部输入
