"""报表流水行内子权限的 name 必须带 TAB（2026-10-12 用户报障回归）。

背景：/user「分配权限」弹窗里「订单流水」模块下挂着 8 个行内操作子权限（迁移
075/079 补种），name 原先全是「编辑」「删除」——所属 TAB 只编码在 code 前缀
（order_ / stockout_ / deduction_ / return_），界面上四个「编辑」长得一模一样，
管理员分不清自己授的是哪个 TAB 的操作权。

修复落在两处，必须口径一致：
  - 存量库：迁移 pg_standalone_090_report_row_action_permission_names 改 name；
  - 空库重建：scripts/init_permissions.py 的 report.children 同步改名。

本测试锁住「两处一致」：任一处单独改动即变红（否则空库与存量库的权限名会漂移）。
"""

import importlib.util
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION = (
    _REPO_ROOT / "migrations" / "versions" / "pg_standalone_090_report_row_action_permission_names.py"
)
_INIT_PERMS = _REPO_ROOT / "scripts" / "init_permissions.py"

# 手工推导的期望名：对齐报表页 tab 文案
# （frontend-vite/src/views/report/composables/useReportConfig.ts 的 TAB_CONFIG.label：
#   order=订单流水、stockin=备货流水、stockout=出货流水、deduction=备货抵扣流水、return=退货流水）。
# order_* 被「订单流水」「备货流水」两个 tab 共用（useReportRowActions.TAB_ROW_PERMISSIONS）。
_EXPECTED = {
    "order_edit": "编辑订单/备货流水",
    "order_delete": "删除订单/备货流水",
    "stockout_edit": "编辑出货流水",
    "stockout_delete": "删除出货流水",
    "deduction_edit": "编辑备货抵扣流水",
    "deduction_delete": "删除备货抵扣流水",
    "return_edit": "编辑退货流水",
    "return_delete": "删除退货流水",
}


def _load_migration():
    """按文件路径加载迁移模块（migrations/versions 不是包，不能用 import 语句）。"""
    spec = importlib.util.spec_from_file_location("mig_090_report_row_action_names", _MIGRATION)
    assert spec is not None and spec.loader is not None, f"无法加载迁移文件：{_MIGRATION}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_renames_each_code_to_its_tab_name():
    renames = {code: new_name for code, new_name, _old in _load_migration()._RENAMES}
    assert renames == _EXPECTED


def test_migration_downgrade_restores_generic_names():
    """downgrade 必须还原成旧名，否则回滚会留下改不回去的状态。"""
    assert {old for _c, _n, old in _load_migration()._RENAMES} == {"编辑", "删除"}


def test_init_permissions_matches_migration():
    """空库重建口径必须与迁移一致（少改一处就会漂移）。"""
    text = _INIT_PERMS.read_text(encoding="utf-8")
    missing = [
        f"{code} -> {name}"
        for code, name in _EXPECTED.items()
        if f"{{'code': '{code}', 'name': '{name}'}}" not in text
    ]
    assert not missing, (
        "scripts/init_permissions.py 与迁移 pg_standalone_090 的权限名不一致，缺：\n  "
        + "\n  ".join(missing)
        + "\n改名必须同时改迁移（存量库）与 init_permissions（空库重建）。"
    )
