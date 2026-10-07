"""报表流水行内「编辑/删除」独立权限点（挂 订单流水 report_manage 之下）

背景：报表页行内编辑/删除（2026-10-06 自客户订单记录查询 tab 迁入）最初沿用
``order_manage``（客户订单）一把粗锁，管理员无法在 /user 单独控制这两个操作。
本迁移按既有「父权限+子权限」范式（pg_standalone_043 的 batch_manage→batch_import、
beile_order_view→导出/打印/确认）在「订单流水」(report_manage, /report 页面自身的
权限项) 下补种两个职责分离子码——子项挂在页面权限之下，勾选操作权限时经前端
级联自动带上页面入口：

    order_edit   编辑   → 报表流水行内编辑（订单 PUT /orders/edit、抵扣 /orders/deduct、
                          备货 PUT /stock/in/edit）与还原数据源 GET /orders/records
    order_delete 删除   → 报表流水行内删除（DELETE /orders/delete、DELETE /stock/in/delete）

配套：user.py 的 NO_MANAGE_INHERIT 必须同时收编这两个码——否则持有「订单流水」的
用户会经 has_permission 的子权限继承自动获得编辑/删除（四眼原则，参考
outsource_ship/receive 的先例），显式勾选才算数。

幂等：按 code 唯一约束，NOT EXISTS 守卫，重复执行安全。

Revision ID: pg_standalone_075_order_row_action_permissions
Revises: pg_standalone_074_related_id_widen
Create Date: 2026-10-07
"""
from alembic import op

revision = 'pg_standalone_075_order_row_action_permissions'
down_revision = 'pg_standalone_074_related_id_widen'
branch_labels = None
depends_on = None

# 列值对齐既有子权限行范式（batch_import / outsource_ship）：icon/url 为空、
# is_nav=False（子码不进导航）、section/排序继承父行（按 code 定位父级，不写死 id）。
_ROWS = [
    ("order_edit", "编辑", 1),
    ("order_delete", "删除", 2),
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
    op.execute("DELETE FROM user_permission WHERE permission_id IN "
               "(SELECT id FROM permission WHERE code IN ('order_edit', 'order_delete'))")
    op.execute("DELETE FROM permission WHERE code IN ('order_edit', 'order_delete')")
