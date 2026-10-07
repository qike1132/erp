"""报表流水行内「编辑/删除」独立权限点（出货 / 备货抵扣 / 退货，挂 report_manage 之下）

背景：报表页行内编辑/删除（2026-10-06 自记录查询 tab 迁入）在订单/备货两个 tab 已用
``order_edit`` / ``order_delete``（迁移 075）。本轮把同样的行内操作扩展到「出货流水」
「备货抵扣流水」「退货流水」三个 tab，按职责分离补种独立子码——三类流水的写路径与
风险各不相同（出货=独立 stock_out；抵扣=订单驱动的 stock_out，需重算订单状态；
退货=stock_return 软取消），管理员需能在 /user 分别授权。

沿用 075 的「父权限 + 子权限」范式：子项挂在「订单流水」(report_manage) 之下，
is_nav=False（子码不进导航），section/排序继承父行（按 code 定位父级，不写死 id）：

    stockout_edit    编辑   → 出货流水行内编辑（PUT /stock/out/edit/{id}，stockin_id IS NULL）
    stockout_delete  删除   → 出货流水行内删除（DELETE /stock/out/delete/{id}）
    deduction_edit   编辑   → 备货抵扣流水行内编辑（PUT /stock/out/edit/{id}，stockin_id IS NOT NULL）
    deduction_delete 删除   → 备货抵扣流水行内删除（DELETE /stock/out/delete/{id}）
    return_edit      编辑   → 退货流水行内编辑（PUT /stock/return/{id}）
    return_delete    删除   → 退货流水行内取消（DELETE /stock/return/{id}）

配套：shared_models/user.py 的 NO_MANAGE_INHERIT 必须同时收编这 6 个码——否则持有
「订单流水」的用户会经 has_permission 的子权限继承自动获得这些操作（四眼原则，
参考 order_edit/order_delete 与 outsource_ship/receive 的先例），显式勾选才算数。

幂等：按 code 唯一约束，NOT EXISTS 守卫，重复执行安全。

Revision ID: pg_standalone_079_report_flow_row_action_permissions
Revises: pg_standalone_078_stock_nav_rename
Create Date: 2026-10-07
"""
from alembic import op

revision = 'pg_standalone_079_report_flow_row_action_permissions'
down_revision = 'pg_standalone_078_stock_nav_rename'
branch_labels = None
depends_on = None

# 列值对齐既有子权限行范式（order_edit / order_delete / batch_import）：
# icon/url 为空、is_nav=False、section/排序继承父行（按 code 定位父级，不写死 id）。
# sort_offset 接在 075 的 +1/+2 之后（+3..+8），避免与既有子行排序冲突。
_ROWS = [
    ("stockout_edit", "编辑", 3),
    ("stockout_delete", "删除", 4),
    ("deduction_edit", "编辑", 5),
    ("deduction_delete", "删除", 6),
    ("return_edit", "编辑", 7),
    ("return_delete", "删除", 8),
]


def upgrade() -> None:
    for code, name, sort_offset in _ROWS:
        op.execute(
            "INSERT INTO permission (code, name, parent_id, section, section_name, sort_order, is_nav) "
            "SELECT '" + code + "', '" + name + "', p.id, p.section, p.section_name, p.sort_order + " + str(sort_offset) + ", False "
            "FROM permission p WHERE p.code = 'report_manage' "
            "AND NOT EXISTS (SELECT 1 FROM permission WHERE code = '" + code + "')"
        )  # nosec B608 — 常量表插值，无外部输入


def downgrade() -> None:
    # 仅删权限点本身：user_permission 关联行由外键级联清理；已分配该码的授权随行消失
    _codes = "', '".join(code for code, _, _ in _ROWS)
    op.execute("DELETE FROM user_permission WHERE permission_id IN "
               f"(SELECT id FROM permission WHERE code IN ('{_codes}'))")
    op.execute(f"DELETE FROM permission WHERE code IN ('{_codes}')")
