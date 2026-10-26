"""H1 回归锁：客户级已出货汇总不得恒为 0。

背景（2026-10-26 上线前检查 H1）
-------------------------------
`shipped_qty` 来自 `_calc_all_shipped_qty`，是 (customer, product_name) 的**整月总量**：
同一客户同一产品有多条 plan 行时，每行都带同一个值。因此两级汇总都必须按该键
去重、每键只计一次。

原实现：total 循环里 `if _key not in _counted_shipped: add(_key); total += ...`，
客户级再判同一个集合 —— 该条件恒 False，`customer_summary[cn]['shipped_qty']`
永远是 0（总计却是对的），排产页按客户看的出货进度整体为 0。

现有 `test_production_plan.py` mock 整个 service，从未执行真实汇总，所以没拦住。
本文件直接调用纯函数 `_calc_monthly_summary`。
"""
from __future__ import annotations

from fastapi_app.services.production_plan_service import _calc_monthly_summary


def _row(customer: str, product: str, *, qty: int, shipped: int,
         stock_status: str = 'normal', remaining: int = 0) -> dict:
    return {
        'customer_name': customer, 'product_name': product,
        'quantity': qty, 'inventory_qty': 0, 'shipped_qty': shipped,
        'remaining_qty': remaining, 'stock_status': stock_status,
    }


def test_customer_shipped_not_zero_for_single_row():
    """最小用例：一行数据客户级也必须等于总出货量（原实现此处为 0）。"""
    summary = _calc_monthly_summary([_row('客户A', '产品X', qty=10, shipped=7)])

    assert summary['total_shipped_qty'] == 7
    assert summary['customer_summary']['客户A']['shipped_qty'] == 7, \
        '客户级出货量恒 0 是本项 bug 的直接指纹'


def test_same_key_multiple_plans_counted_once_at_both_levels():
    """同客户同产品的两条计划：总计与客户级都只能计 7（不是 0，也不是 14）。"""
    rows = [
        _row('客户A', '产品X', qty=10, shipped=7),
        _row('客户A', '产品X', qty=5, shipped=7),
    ]

    summary = _calc_monthly_summary(rows)

    assert summary['total_shipped_qty'] == 7, '整月总量被重复累加会把 7 放大成 14'
    assert summary['customer_summary']['客户A']['shipped_qty'] == 7


def test_customer_level_sums_across_distinct_products():
    """同一客户的多个产品各计一次，客户级 = 各产品之和；不同客户互不串。"""
    rows = [
        _row('客户A', '产品X', qty=10, shipped=7),
        _row('客户A', '产品Y', qty=10, shipped=3),
        _row('客户B', '产品X', qty=10, shipped=5),
    ]

    summary = _calc_monthly_summary(rows)

    assert summary['total_shipped_qty'] == 15
    assert summary['customer_summary']['客户A']['shipped_qty'] == 10
    assert summary['customer_summary']['客户B']['shipped_qty'] == 5


def test_plan_and_inventory_totals_still_accumulate_per_row():
    """去重只作用于 shipped_qty：计划量/库存/剩余仍按行累加（防过度收敛）。"""
    rows = [
        _row('客户A', '产品X', qty=10, shipped=7, remaining=3),
        _row('客户A', '产品X', qty=5, shipped=7, remaining=0),
    ]

    summary = _calc_monthly_summary(rows)

    assert summary['total_plan_qty'] == 15
    assert summary['customer_summary']['客户A']['plan_qty'] == 15
    assert summary['customer_summary']['客户A']['remaining_qty'] == 3
