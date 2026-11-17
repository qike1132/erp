"""退货列表日期区间右边界（2026-11-17 上线前审计 P1-5）。

## 拦哪种出错

`get_stockreturns` 的 `end_date` 右边界原先写 `< ed + timedelta(days=1)`，而 `ed`
本身已经是**当天 23:59:59**（`_day_range_utc(..., end=True)` 的产物）—— 再加一天，
右边界就成了**次日 23:59:59**：选「截至 10-17」时 10-18 整天的退货被算进列表，
`total` 与导出对账同步多算。区间越长多算的越多，且单据本身看起来完全合法。

`stock_return` 当时实测 0 行（审计 §10.9 X-7），所以线上还没开始错；但「开始用退货
的第一天就错」，故随批次 2 一起修。

## 本文件锁什么

用真实测试库（`sr_api` 夹具的会话，跑完整体回滚）造三行退货：

- `10-16 12:00`（早于起日，不该出现）
- `10-17 23:59:59.5`（起日最后一秒内，**必须出现** —— 这是当年加 `days=1` 想解决的
  「微秒记录漏掉」问题的正确解法，不能被这次修复顺手丢掉）
- `10-18 00:00:00`（次日零点，**不该出现** —— 就是 off-by-one 的那一天）

断言 `start_date=end_date=10-17` 时 `total == 1` 且只有中间那行。修复前第三条会被
算进来（`total == 2`），用例变红。
"""
from datetime import UTC, datetime, timedelta, timezone

import pytest
from test_stock_return_api import sr_api as _api_fixture

from fastapi_app.services.stock_inventory_service import get_stockreturns
from fastapi_app.shared_models import Product, StockReturn

# pytest 按模块属性名注册导入的夹具
sr_api = _api_fixture

# 北京时区（东八区无夏令时；与 stock_inventory_service._BUSINESS_TZ 同义）
_BJ = timezone(timedelta(hours=8))


def _bj(y: int, mo: int, d: int, h: int = 0, mi: int = 0, s: int = 0, us: int = 0) -> datetime:
    return datetime(y, mo, d, h, mi, s, us, tzinfo=_BJ).astimezone(UTC)


@pytest.mark.integration
async def test_end_date_includes_whole_day_but_not_next_day(sr_api):
    _client, db, _ = sr_api
    suffix = datetime.now(UTC).strftime('%H%M%S%f')
    customer = f'退货区间客户-{suffix}'

    product = Product(name=f'退货区间产品-{suffix}', current_stock=0)
    db.add(product)
    await db.flush()

    rows = {
        'before': StockReturn(
            return_no=f'SR-DR-{suffix}-1', product_id=product.id, quantity=1,
            customer=customer, status='active', return_date=_bj(2026, 10, 16, 12, 0),
        ),
        # 起日 23:59:59.5 —— 微秒记录，`<= 当天 23:59:59` 的口径会漏掉它
        'last_second': StockReturn(
            return_no=f'SR-DR-{suffix}-2', product_id=product.id, quantity=2,
            customer=customer, status='active', return_date=_bj(2026, 10, 17, 23, 59, 59, 500000),
        ),
        # 次日 00:00 整 —— off-by-one 多算的那一天的第一秒
        'next_day': StockReturn(
            return_no=f'SR-DR-{suffix}-3', product_id=product.id, quantity=3,
            customer=customer, status='active', return_date=_bj(2026, 10, 18, 0, 0),
        ),
    }
    for row in rows.values():
        db.add(row)
    await db.flush()

    payload = await get_stockreturns(
        db, page=1, per_page=50, customer=customer,
        start_date='2026-10-17', end_date='2026-10-17',
    )

    got = [item['id'] for item in payload['items']]
    assert payload['total'] == 1, (
        f"end_date=2026-10-17 应只命中当天 1 行，实际 total={payload['total']} "
        f"（多出来的那行就是被算进去的次日）"
    )
    assert got == [rows['last_second'].id], (
        f"当天最后一秒内的退货被漏掉或被次日顶替：{got} "
        f"(before={rows['before'].id} last_second={rows['last_second'].id} "
        f"next_day={rows['next_day'].id})"
    )


@pytest.mark.integration
async def test_start_bound_still_left_closed(sr_api):
    """左边界不受影响：起日 00:00:00 整的那行必须命中（防把左闭改坏）。"""
    _client, db, _ = sr_api
    suffix = datetime.now(UTC).strftime('%H%M%S%f')
    customer = f'退货左界客户-{suffix}'

    product = Product(name=f'退货左界产品-{suffix}', current_stock=0)
    db.add(product)
    await db.flush()

    midnight = StockReturn(
        return_no=f'SR-DL-{suffix}', product_id=product.id, quantity=1,
        customer=customer, status='active', return_date=_bj(2026, 10, 17, 0, 0),
    )
    db.add(midnight)
    await db.flush()

    payload = await get_stockreturns(
        db, page=1, per_page=50, customer=customer,
        start_date='2026-10-17', end_date='2026-10-17',
    )

    assert payload['total'] == 1, payload
    assert [item['id'] for item in payload['items']] == [midnight.id]
