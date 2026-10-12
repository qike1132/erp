"""报表流水行内权限按 TAB 拆成 5 对：新增「备货流水」独立码 + 全部改名/重排

背景：/report 页共 5 个 tab（订单流水 / 备货流水 / 出货流水 / 备货抵扣流水 / 退货流水），
但行内「编辑/删除」原先只有 4 对独立码——「备货流水」借用了 order_edit / order_delete。
于是 /user「分配权限」里这 8 条子权限的 name 全是「编辑」「删除」，只靠 code 前缀区分，
管理员分不清自己授的是哪个 TAB（2026-10-12 用户报障）。

本次把授权模型对齐 tab 结构：

    订单流水      order_edit / order_delete          编辑订单流水 / 删除订单流水
    备货流水      stockin_edit / stockin_delete      编辑备货流水 / 删除备货流水   ← 新增
    出货流水      stockout_edit / stockout_delete    编辑出货流水 / 删除出货流水
    备货抵扣流水  deduction_edit / deduction_delete  编辑备货抵扣流水 / 删除备货抵扣流水
    退货流水      return_edit / return_delete        编辑退货流水 / 删除退货流水

sort_order 重排为 +1..+10，对齐 tab 顺序（user_service.get_permissions 按 sort_order
排 children）。

**存量授权刻意不回填**（2026-10-12 用户拍板「干净起步」）：order_edit / order_delete
原先顺带放行备货流水的行内编辑/删除（stock.py 的
require_any_permission('stockin_manage','order_manage','order_edit')），拆码后这些路径
改判 stockin_*。只持有 order_edit / order_delete 的用户会因此失去备货流水的行内编辑/
删除（仍持有 order_manage 或 stockin_manage 的不受影响），需在 /user 重新分配。

配套（同一提交，缺一处就会前后端 403 口径不一致）：
- fastapi_app/shared_models/user.py 的 NO_MANAGE_INHERIT 收编两个新码（四眼原则）；
- stock.py /in/edit、/in/delete 改判 stockin_*；
- order.py /orders/records（行内操作前的聚合行还原）、auxiliary.py 的备货量提示；
- 前端 useReportRowActions.TAB_ROW_PERMISSIONS.stockin 改判 stockin_*。

幂等：INSERT 用 NOT EXISTS 守卫；UPDATE 按 code 定位；重复执行安全。
downgrade：删两个新码（user_permission 关联行由外键级联清理）并把名字/排序还原到
075/079 的状态。

Revision ID: pg_standalone_091_report_row_action_per_tab
Revises: pg_standalone_090_report_row_action_permission_names
Create Date: 2026-10-12
"""
from alembic import op

revision = 'pg_standalone_091_report_row_action_per_tab'
down_revision = 'pg_standalone_090_report_row_action_permission_names'
branch_labels = None
depends_on = None

# 目标态：(code, name, sort_offset)。顺序 = /report 的 tab 顺序。
_ROWS = [
    ('order_edit', '编辑订单流水', 1),
    ('order_delete', '删除订单流水', 2),
    ('stockin_edit', '编辑备货流水', 3),
    ('stockin_delete', '删除备货流水', 4),
    ('stockout_edit', '编辑出货流水', 5),
    ('stockout_delete', '删除出货流水', 6),
    ('deduction_edit', '编辑备货抵扣流水', 7),
    ('deduction_delete', '删除备货抵扣流水', 8),
    ('return_edit', '编辑退货流水', 9),
    ('return_delete', '删除退货流水', 10),
]

# 本次新增的两个码（需 INSERT；其余为既有行，只 UPDATE）
_NEW_CODES = {'stockin_edit', 'stockin_delete'}

# 回滚态：075/079 的原始名字与排序（090 只改过 name，排序仍是 075/079 的 +1..+8）
_OLD_ROWS = [
    ('order_edit', '编辑', 1),
    ('order_delete', '删除', 2),
    ('stockout_edit', '编辑', 3),
    ('stockout_delete', '删除', 4),
    ('deduction_edit', '编辑', 5),
    ('deduction_delete', '删除', 6),
    ('return_edit', '编辑', 7),
    ('return_delete', '删除', 8),
]

# sort_order 以父行 report_manage 为基准偏移（与 075/079 同口径，不写死父 id）
_BASE_SORT = "(SELECT p.sort_order FROM permission p WHERE p.code = 'report_manage')"


def upgrade() -> None:
    # 1) 补种备货流水的两个独立码（挂 report_manage 之下，列值对齐既有子权限行范式）
    for code, name, offset in _ROWS:
        if code not in _NEW_CODES:
            continue
        op.execute(
            "INSERT INTO permission (code, name, parent_id, section, section_name, sort_order, is_nav) "
            "SELECT '" + code + "', '" + name + "', p.id, p.section, p.section_name, p.sort_order + " + str(offset) + ", False "
            "FROM permission p WHERE p.code = 'report_manage' "
            "AND NOT EXISTS (SELECT 1 FROM permission WHERE code = '" + code + "')"
        )  # nosec B608 — 常量表插值，无外部输入

    # 2) 10 条统一改名 + 重排 sort_order，对齐 /report 的 tab 顺序
    for code, name, offset in _ROWS:
        op.execute(
            "UPDATE permission SET name = '" + name + "', sort_order = " + _BASE_SORT + " + " + str(offset) + " "
            "WHERE code = '" + code + "'"
        )  # nosec B608 — 常量表插值，无外部输入


def downgrade() -> None:
    # 1) 名字 / 排序还原到 075/079 的状态
    for code, name, offset in _OLD_ROWS:
        op.execute(
            "UPDATE permission SET name = '" + name + "', sort_order = " + _BASE_SORT + " + " + str(offset) + " "
            "WHERE code = '" + code + "'"
        )  # nosec B608
    # 2) 删除本次新增的两个码（user_permission 关联行由外键级联清理）
    codes = "', '".join(sorted(_NEW_CODES))
    op.execute(
        "DELETE FROM user_permission WHERE permission_id IN "
        f"(SELECT id FROM permission WHERE code IN ('{codes}'))"
    )
    op.execute(f"DELETE FROM permission WHERE code IN ('{codes}')")
