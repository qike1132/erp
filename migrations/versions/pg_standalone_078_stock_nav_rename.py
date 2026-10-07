"""导航项「订单列表」改名为「订单查询」

背景：/stock 页承载订单/库存汇总（原「库存查询」标题+图标已于 2026-10-07
从页头移除；「库存查询」已独立到 /inventory-query，见迁移 076）。
2026-10-07 业务要求：左侧导航项「订单列表」（code=stock_view, url=stock.inventory）
改名为「订单查询」。

注意：该项所属分区 section_name 已为「订单查询」（section=data），改名后
分区标题与项名相同 —— 系业务确认（见提交说明）。

幂等：按 code 精确定位；若名称已是目标值则不匹配、无操作。

Revision ID: pg_standalone_078_stock_nav_rename
Revises: pg_standalone_078_drop_inventory_query_route
Create Date: 2026-10-07
"""
from alembic import op

revision = 'pg_standalone_078_stock_nav_rename'
# 接在 078_drop 之后（二者原本都挂在 077 下，形成两个 head 会让
# alembic upgrade head 报 Multiple head revisions —— scripts/check_alembic_heads.py 门禁）。
down_revision = 'pg_standalone_078_drop_inventory_query_route'
branch_labels = None
depends_on = None

_CODE = 'stock_view'
_OLD_NAME = '订单列表'
_NEW_NAME = '订单查询'


def upgrade() -> None:
    op.execute(
        "UPDATE permission SET name = '" + _NEW_NAME + "', updated_at = now() "
        "WHERE code = '" + _CODE + "' AND name = '" + _OLD_NAME + "'"
    )  # nosec B608 — 常量表插值，无外部输入


def downgrade() -> None:
    op.execute(
        "UPDATE permission SET name = '" + _OLD_NAME + "', updated_at = now() "
        "WHERE code = '" + _CODE + "' AND name = '" + _NEW_NAME + "'"
    )  # nosec B608 — 常量表插值，无外部输入
