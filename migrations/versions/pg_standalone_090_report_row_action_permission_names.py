"""报表流水行内「编辑/删除」子权限改名：把 TAB 写进 name

背景：/user「分配权限」弹窗里「订单流水」模块下挂着 8 个行内操作子权限（迁移 075/079
补种），但它们的 ``name`` 全是「编辑」「删除」——所属 TAB 只编码在 ``code`` 前缀
（order_ / stockout_ / deduction_ / return_），界面上四个「编辑」长得一模一样，
管理员分不清自己授的是哪个 TAB 的操作权（2026-10-12 用户报障）。

``code`` 是功能键（前后端 hasPermission / require_any_permission 都按 code 判定），
``name`` 仅用于展示，故**只改 name**。命名对齐报表页 tab 文案
（frontend-vite/src/views/report/composables/useReportConfig.ts 的 TAB_CONFIG.label）：

    order_edit / order_delete         → 订单/备货流水（这两个 tab 共用该码，见
                                        useReportRowActions.TAB_ROW_PERMISSIONS）
    stockout_edit / stockout_delete   → 出货流水
    deduction_edit / deduction_delete → 备货抵扣流水
    return_edit / return_delete       → 退货流水

幂等：按 code 定位（code 有唯一约束），重复执行安全；行不存在时更新 0 行。
配套：scripts/init_permissions.py 的同名子项已同步改名，保证空库重建也一致
（fastapi_app/tests/test_report_row_action_permission_names.py 锁住两处一致）。

Revision ID: pg_standalone_090_report_row_action_permission_names
Revises: d8d44bd23640
Create Date: 2026-10-12
"""
from alembic import op

revision = 'pg_standalone_090_report_row_action_permission_names'
down_revision = 'd8d44bd23640'
branch_labels = None
depends_on = None

# (code, 新名, 旧名)——旧名供 downgrade 还原
_RENAMES = [
    ('order_edit', '编辑订单/备货流水', '编辑'),
    ('order_delete', '删除订单/备货流水', '删除'),
    ('stockout_edit', '编辑出货流水', '编辑'),
    ('stockout_delete', '删除出货流水', '删除'),
    ('deduction_edit', '编辑备货抵扣流水', '编辑'),
    ('deduction_delete', '删除备货抵扣流水', '删除'),
    ('return_edit', '编辑退货流水', '编辑'),
    ('return_delete', '删除退货流水', '删除'),
]


def _rename(to_new: bool) -> None:
    """按 code 批量改名；to_new=False 时还原为旧名（downgrade）。"""
    for code, new_name, old_name in _RENAMES:
        target = new_name if to_new else old_name
        op.execute(
            "UPDATE permission SET name = '" + target + "' WHERE code = '" + code + "'"
        )  # nosec B608 — 常量表插值，无外部输入


def upgrade() -> None:
    _rename(True)


def downgrade() -> None:
    _rename(False)
