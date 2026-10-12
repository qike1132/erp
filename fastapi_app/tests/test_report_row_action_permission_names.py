"""报表流水行内子权限：一个 TAB 一对「编辑/删除」，名字与 TAB 一致、判权码同步。

背景：/report 共 5 个 tab（订单流水 / 备货流水 / 出货流水 / 备货抵扣流水 / 退货流水），
但行内「编辑/删除」原先只有 4 对独立码——备货流水借用了 order_edit / order_delete，
且 8 条子权限的 name 全是「编辑」「删除」，/user「分配权限」里分不清授的是哪个 TAB
（2026-10-12 用户报障）。

修复落在三处，必须口径一致：
  - 存量库：迁移 pg_standalone_091_report_row_action_per_tab（改名 + 新增 stockin_* + 重排）
  - 空库重建：scripts/init_permissions.py 的 report.children
  - 判权：stock.py /in/edit|delete 改判 stockin_*（不再放行 order_*）

本测试锁住这三处；任一处单独改动即变红。
"""

import importlib.util
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION = (
    _REPO_ROOT / "migrations" / "versions" / "pg_standalone_091_report_row_action_per_tab.py"
)
_INIT_PERMS = _REPO_ROOT / "scripts" / "init_permissions.py"
_STOCK_ENDPOINTS = _REPO_ROOT / "fastapi_app" / "api" / "v1" / "endpoints" / "stock.py"

# 手工推导的期望名：与报表页 tab 文案逐字一致
# （frontend-vite/src/views/report/composables/useReportConfig.ts 的 TAB_CONFIG.label：
#   order=订单流水、stockin=备货流水、stockout=出货流水、deduction=备货抵扣流水、return=退货流水）。
_EXPECTED = {
    "order_edit": "编辑订单流水",
    "order_delete": "删除订单流水",
    "stockin_edit": "编辑备货流水",
    "stockin_delete": "删除备货流水",
    "stockout_edit": "编辑出货流水",
    "stockout_delete": "删除出货流水",
    "deduction_edit": "编辑备货抵扣流水",
    "deduction_delete": "删除备货抵扣流水",
    "return_edit": "编辑退货流水",
    "return_delete": "删除退货流水",
}


def _load_migration():
    """按文件路径加载迁移模块（migrations/versions 不是包，不能用 import 语句）。"""
    spec = importlib.util.spec_from_file_location("mig_091_report_row_action_per_tab", _MIGRATION)
    assert spec is not None and spec.loader is not None, f"无法加载迁移文件：{_MIGRATION}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_names_each_code_after_its_tab():
    rows = {code: name for code, name, _offset in _load_migration()._ROWS}
    assert rows == _EXPECTED


def test_migration_adds_exactly_the_stockin_pair():
    """备货流水原先没有自己的码（借用 order_*），本次只新增这一对。"""
    assert set(_load_migration()._NEW_CODES) == {"stockin_edit", "stockin_delete"}


def test_migration_downgrade_restores_generic_names():
    """downgrade 必须还原 075/079 的旧名与排序，否则回滚会留下改不回去的状态。"""
    mig = _load_migration()
    assert {name for _c, name, _o in mig._OLD_ROWS} == {"编辑", "删除"}
    assert {c for c, _n, _o in mig._OLD_ROWS} == set(_EXPECTED) - set(mig._NEW_CODES)


def test_init_permissions_matches_migration():
    """空库重建口径必须与迁移一致（少改一处就会漂移）。"""
    text = _INIT_PERMS.read_text(encoding="utf-8")
    missing = [
        f"{code} -> {name}"
        for code, name in _EXPECTED.items()
        if f"{{'code': '{code}', 'name': '{name}'}}" not in text
    ]
    assert not missing, (
        "scripts/init_permissions.py 与迁移 pg_standalone_091 的权限名不一致，缺：\n  "
        + "\n  ".join(missing)
        + "\n改名必须同时改迁移（存量库）与 init_permissions（空库重建）。"
    )


def test_stockin_endpoints_gate_on_stockin_codes_not_order_codes():
    """备货流水的行内编辑/删除必须判 stockin_*，不得再放行 order_*。

    这里走源码断言而不是 HTTP 往返：这两条端点的判权写在装饰器的
    require_any_permission 里，跑 HTTP 层需要「只有某个权限」的用户夹具
    （现有 auth_headers 是超管，会绕过判权）；而本测试要拦的回归恰恰是
    「有人把 order_* 加回备货端点」——源码断言能直接拦下，且失败信息明确。
    """
    src = _STOCK_ENDPOINTS.read_text(encoding="utf-8")
    assert "'stockin_manage', 'order_manage', 'stockin_edit'" in src, (
        "备货编辑端点未改判 stockin_edit"
    )
    assert "'stockin_manage', 'order_manage', 'stockin_delete'" in src, (
        "备货删除端点未改判 stockin_delete"
    )
    assert "'stockin_manage', 'order_manage', 'order_edit'" not in src, (
        "备货编辑端点仍在放行 order_edit（拆码后不该再有）"
    )
    assert "'stockin_manage', 'order_manage', 'order_delete'" not in src, (
        "备货删除端点仍在放行 order_delete（拆码后不该再有）"
    )
