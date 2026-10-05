"""P1-a 第 2 层：导入幂等键（inventory_log.idem_key）的单元与结构守卫。

- 单元：_import_idem_key 的口径（前缀/客户/产品/数量/业务日）。
- 结构（AST）：导入路径里**每一处** InventoryLog 构造都必须带 idem_key ——
  防止未来某个导入分支漏填而静默失去 DB 层幂等保护（本仓惯用的 AST 守卫手法，
  参见 test_product_stock_check_constraint 等）。
"""
import ast
from datetime import UTC, datetime
from pathlib import Path

from fastapi_app.services.batch_import_core import _import_idem_key

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SVC = _REPO_ROOT / 'fastapi_app' / 'services'
# 所有「导入来源」写 InventoryLog 的模块（手工/审批/建品等路径不在此列，
# 它们本就不设 idem_key）。
# ⚠️ 已知未接第 2 层且**不在此列**：fastapi_app/tasks/batch_tasks.py 的
#    /tasks/import-orders|stockins（ARQ 异步导入，前端无调用，缺口已在
#    import_guard.py 留档）。将来若接线，本清单需同步。
_IMPORT_MODULES = [
    _SVC / 'batch_import_service.py',
    _SVC / 'batch_import_core.py',
    _SVC / 'staging' / 'order.py',
    _SVC / 'staging' / 'stockin.py',
    _SVC / 'staging' / 'stockout.py',
]


# ---------------------------------------------------------------------------
# 单元：键口径
# ---------------------------------------------------------------------------
def test_key_format_includes_prefix_customer_product_qty_date():
    when = datetime(2026, 10, 5, 13, 0, tzinfo=UTC)
    assert _import_idem_key('stockout', '客户A', 42, 100, when) == 'stockout:客户A|42|100|2026-10-05'


def test_key_strips_customer_whitespace():
    when = datetime(2026, 10, 5, tzinfo=UTC)
    assert _import_idem_key('order', '  客户A  ', 1, 5, when) == 'order:客户A|1|5|2026-10-05'


def test_key_differs_by_day():
    """日期必须入键：不同日的同客户同产品同数量是合法重复，不得撞键。"""
    a = _import_idem_key('stockout', 'C', 1, 10, datetime(2026, 10, 5, tzinfo=UTC))
    b = _import_idem_key('stockout', 'C', 1, 10, datetime(2026, 10, 6, tzinfo=UTC))
    assert a != b


def test_key_differs_by_prefix():
    when = datetime(2026, 10, 5, tzinfo=UTC)
    assert _import_idem_key('order', 'C', 1, 10, when) != _import_idem_key('stockin', 'C', 1, 10, when)


def test_key_is_deterministic():
    when = datetime(2026, 10, 5, tzinfo=UTC)
    assert _import_idem_key('stockout', 'C', 1, 10, when) == _import_idem_key(
        'stockout', 'C', 1, 10, when
    )


# ---------------------------------------------------------------------------
# 结构守卫：导入路径的每个 InventoryLog 都必须带 idem_key
# ---------------------------------------------------------------------------
def _inventory_log_calls(path: Path) -> list[ast.Call]:
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    calls = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == 'InventoryLog'
        ):
            calls.append(node)
    return calls


def test_every_import_inventory_log_sets_idem_key():
    offenders: list[str] = []
    total = 0
    for path in _IMPORT_MODULES:
        for call in _inventory_log_calls(path):
            total += 1
            kwargs = {kw.arg for kw in call.keywords}
            if 'idem_key' not in kwargs:
                offenders.append(f'{path.name}:{call.lineno}')
    assert total >= 9, f'预期至少 9 处导入 InventoryLog 构造，实际 {total}（盘点是否遗漏路径）'
    assert not offenders, f'以下 InventoryLog 未设置 idem_key，将失去 DB 层幂等保护: {offenders}'


def test_aware_and_naive_yield_same_local_day_key():
    """aware(UTC) 与 naive 必须收敛到同一个本地日历日 —— 否则跨路径/跨零点漏拦。

    本机 UTC+8：UTC 日与本地日在 00:00--08:00 之间不同。键若直接 .date() 会分叉。
    注意：断言依赖运行时区非零偏移，在 UTC 机器上是空转（固有弱点）。
    """
    # 取一个「UTC 日与本地日必然不同」的时刻（本地 07:00 = UTC 前一日 23:00）
    local = datetime(2026, 10, 5, 7, 0).astimezone()
    aware = local.astimezone(UTC)
    naive = datetime(2026, 10, 5, 7, 0)  # 同一本地壁钟时间的 naive 形态
    assert _import_idem_key('order', 'C', 1, 10, aware) == _import_idem_key('order', 'C', 1, 10, naive)


# ---------------------------------------------------------------------------
# 结构守卫：行级 except 必须捕获 SQLAlchemyError
# ---------------------------------------------------------------------------
_STAGING_CONFIRM_MODULES = [
    _SVC / 'staging' / 'order.py',
    _SVC / 'staging' / 'stockin.py',
    _SVC / 'staging' / 'stockout.py',
]


def _except_names(path: Path) -> list[set[str]]:
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and isinstance(node.type, ast.Tuple):
            names = {e.id for e in node.type.elts if isinstance(e, ast.Name)}
            if names:
                out.append(names)
    return out


def test_oserror_handlers_also_catch_sqlalchemy_error():
    """凡捕获 OSError 的 except 必须同时捕获 SQLAlchemyError。

    H-1 根因（第四轮实测）：staging 三条确认路径的行级 except 原为
    (ValueError, TypeError, OSError)，幂等键 IntegrityError 穿透它 → 冒到
    db_transaction → 整批回滚 500 + 该行永远无法确认。此断言防止再次漏掉。
    """
    offenders: list[str] = []
    for path in _STAGING_CONFIRM_MODULES:
        for names in _except_names(path):
            if 'OSError' in names and 'SQLAlchemyError' not in names:
                offenders.append(path.name)
    assert not offenders, f'以下模块的 except 捕获 OSError 但漏 SQLAlchemyError（幂等冲突会穿透）: {offenders}'
