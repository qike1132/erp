"""L-9（2026-11-21 审计）：magnified_purchase_qty 的 JS Math.round 舍入口径变异锁。

实现（purchase_utils.magnified_purchase_qty）刻意与前端 `magnifyByLossRate`
逐字同源：`floor(x*100 + 0.5)/100`——对正数等价 JS `Math.round`，**不是**
Python 内置 round（银行家舍入）。docstring 已声明这是刻意同源，实现不改；
本文件把 `.5` 边界写成字面量期望锁死，变异检查：

- 把实现改成 Python `round()` → 2.125/0% 边界得 2.12，test_half_rounds_up 变红；
- 把实现改成截断 `int()` → 同一用例得 2.12，同样变红；
- 把实现改成 `ceil()` → 非边界用例（7.77/12.5‰）得 7.88，test_general_cases 变红。

期望值全部是当场实跑（Python 3.11，IEEE-754）取得的**字面量**，不是被测代码算出来的。
"""
from decimal import Decimal

import pytest

from fastapi_app.services.purchase_utils import magnified_purchase_qty


class TestMagnifiedPurchaseQtyRoundingMutationLock:
    """变异锁：`.5` 边界必须「五入」（JS Math.round 口径），非边界值不被放大。"""

    def test_half_rounds_up(self):
        # 2.125 在 IEEE-754 里精确可表示，×100 恰为 212.5 —— `.5` 边界。
        # JS Math.round(212.5) = 213 → 2.13；
        # Python round(212.5) = 212（银行家舍入，取偶）→ 2.12，截断也是 2.12。
        # 实现若被「顺手改整齐」成 round()/int()，此用例必红。
        assert magnified_purchase_qty(2.125, 0) == Decimal('2.13')
        # None 损耗率与显式 0 同义（回退链终点都是 0），边界行为一致。
        assert magnified_purchase_qty(2.125, None) == Decimal('2.13')
        assert magnified_purchase_qty(Decimal('2.125'), Decimal('0')) == Decimal('2.13')

    def test_general_cases_not_inflated(self):
        # 非边界值：普通四舍五入到 2 位，不向上多进一位（防 ceil/恒进位变异）。
        assert magnified_purchase_qty(7.77, 12.5) == Decimal('7.87')
        assert magnified_purchase_qty(3, 30) == Decimal('3.09')
        assert magnified_purchase_qty(10, 5) == Decimal('10.05')
        assert magnified_purchase_qty(1, 50) == Decimal('1.05')

    def test_non_positive_qty_is_zero(self):
        assert magnified_purchase_qty(0, 10) == Decimal('0')
        assert magnified_purchase_qty(-2, 10) == Decimal('0')

    @pytest.mark.parametrize('qty,rate,expected', [
        # 与前端 magnifyByLossRate 同源的对账样例：qty*(1+rate/1000) 后 2 位舍入。
        (Decimal('890'), 1000, Decimal('1780')),
        (Decimal('920'), 15, Decimal('933.8')),
    ])
    def test_front_end_parity_samples(self, qty, rate, expected):
        assert magnified_purchase_qty(qty, rate) == expected
