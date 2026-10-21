"""明细编辑响应改用 FIFO 实时口径（2026-10-17 审计 F2-1〔Z03-主代理闭合〕）。

`purchase_plan_details.shipped_qty` 是 [DEPRECATED] 缓存列：只有出货 recalc
（`_update_shipped_qty`）写它，列表/详情/进度三条读路径一律用 FIFO 实时分配覆盖它。
`update_detail` 是当初漏掉的那条 —— 它把 `detail.to_dict()` 原样返回，缓存列就此
冒充实时值：前端保存后这一行的「已出货/剩余」会跳回和列表不一致的数字。

本文件锁三件事：
1. 响应里的 shipped/remaining 来自 FIFO 实时分配，不是缓存列；
2. 分配结果跟随本次编辑（改数量当次就重算，不需要等下一次出货 recalc）；
3. FIFO 不可用时显式 `fifo_degraded`，且不把缓存列当实时值回给调用方。
"""
from datetime import date, datetime

import pytest

from fastapi_app.services import purchase_plan_shipment
from fastapi_app.services.purchase_plan_crud_ops import update_detail
from fastapi_app.services.purchase_plan_queries import get_plan_detail
from fastapi_app.shared_models import Customer, Product, PurchasePlan, PurchasePlanDetail, StockOut

_SEQ = 0


def _uniq(prefix: str) -> str:
    global _SEQ
    _SEQ += 1
    return f'{prefix}{_SEQ}'


async def _mk_plan_with_two_details(db, *, shipped_total: int, qty_first: int = 10, qty_second: int = 20,
                                    stale_cache: int = 999) -> tuple[PurchasePlan, PurchasePlanDetail, PurchasePlanDetail]:
    """客户 + 产品 + 当月两条明细（前 10 / 后 20）+ 出货 shipped_total 件。

    `stale_cache` 写进两条明细的 shipped_qty 缓存列，制造「缓存列 ≠ 实时分配」的场景 ——
    这就是生产里编辑响应会撒谎的根因形态。
    """
    cust = Customer(name=_uniq('F21-C'), customer_code=_uniq('F21-CC'))
    prod = Product(name=_uniq('F21-P'), barcode=_uniq('F21B'), current_stock=0, initial_stock=0)
    db.add_all([cust, prod])
    await db.flush()

    plan = PurchasePlan(plan_no=_uniq('PP-F21'), plan_month='2026-10', customer_id=cust.id,
                        customer_name=cust.name, status='confirmed')
    db.add(plan)
    await db.flush()

    d1 = PurchasePlanDetail(plan_id=plan.id, product_id=prod.id, product_name=prod.name, barcode=prod.barcode,
                            plan_date=date(2026, 10, 5), quantity=qty_first, shipped_qty=stale_cache)
    d2 = PurchasePlanDetail(plan_id=plan.id, product_id=prod.id, product_name=prod.name, barcode=prod.barcode,
                            plan_date=date(2026, 10, 20), quantity=qty_second, shipped_qty=stale_cache)
    db.add_all([d1, d2])
    if shipped_total > 0:
        db.add(StockOut(stockout_no=_uniq('F21SO'), stockout_date=datetime(2026, 10, 10, 9, 0, 0),
                        product_id=prod.id, quantity=shipped_total, returned_quantity=0, customer=cust.name))
    await db.flush()
    return plan, d1, d2


async def test_edit_response_uses_fifo_not_cache_column(async_db_session):
    """缓存列 = 999，实时分配 = 10/5 → 响应必须回实时值。"""
    db = async_db_session
    _plan, _d1, d2 = await _mk_plan_with_two_details(db, shipped_total=15)

    res = await update_detail(db, d2.id, remark='改备注')

    assert d2.shipped_qty == 999  # 缓存列确实陈旧（前提成立，否则本用例什么都没测）
    assert res['shipped_qty'] == 5
    assert res['remaining_qty'] == 15
    assert res['fifo_degraded'] is False


async def test_edit_response_allocation_follows_new_quantity(async_db_session):
    """把首批 10 改成 4 → 出货 15 的分配当场变成 4/11，响应不能还是旧分配。"""
    db = async_db_session
    _plan, d1, _d2 = await _mk_plan_with_two_details(db, shipped_total=15)

    res = await update_detail(db, d1.id, quantity=4)

    assert res['quantity'] == 4
    assert res['shipped_qty'] == 4
    assert res['remaining_qty'] == 0
    assert res['fifo_degraded'] is False


async def test_edit_response_matches_plan_detail_read_path(async_db_session):
    """编辑响应与详情读路径必须同口径 —— 用户看到的不一致就是从这两处来的。"""
    db = async_db_session
    plan, _d1, d2 = await _mk_plan_with_two_details(db, shipped_total=15)

    res = await update_detail(db, d2.id, remark='再改一次')
    detail_rows = (await get_plan_detail(db, plan.id))['details']
    row = next(r for r in detail_rows if r['id'] == d2.id)

    assert res['shipped_qty'] == row['shipped_qty']
    assert res['remaining_qty'] == row['remaining_qty']


async def test_degraded_fifo_is_flagged_and_cache_not_echoed(async_db_session, monkeypatch):
    """FIFO 查询不可用：置 fifo_degraded，且绝不把缓存列（999）当实时值返回。"""
    db = async_db_session
    _plan, _d1, d2 = await _mk_plan_with_two_details(db, shipped_total=15)

    async def _unavailable(*args, **kwargs):
        raise RuntimeError('FIFO_ALLOCATION_UNAVAILABLE')

    monkeypatch.setattr(purchase_plan_shipment, '_get_shipped_fifo_map', _unavailable)

    res = await update_detail(db, d2.id, remark='降级场景')

    assert res['fifo_degraded'] is True
    assert res['shipped_qty'] != 999
    assert res['shipped_qty'] == 0


async def test_missing_detail_still_raises(async_db_session):
    """守卫没被改坏：不存在的明细仍按原文案报错（本用例防重构把校验顺带删了）。"""
    db = async_db_session
    with pytest.raises(ValueError, match='明细记录不存在'):
        await update_detail(db, 9_999_999, remark='不存在')
