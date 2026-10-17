"""退货 → 成品库存批次可用量联动测试（真库）

锁死用户口径（1000 / 950 / 1000 / 950）：
- 批次入库 1000、该批次已出货 50 → /finished-stock 该行「库存」= 950
- 退货 50 后：批次入库仍 1000（不变），「库存」950 → 1000（只有库存 +50）
- 取消退货 50 后：「库存」对称回到 950

批次可用量由公式实时算出，不引入任何双写：
  批次可用 = SUM(daily_production_record WHERE department='packaging' AND batch_no=B)
          − SUM(stock_out.quantity − stock_out.returned_quantity
                WHERE stockin_id IS NULL AND coalesce(batch_no,'')=B)
退货天然通过写回 stock_out.returned_quantity 使可用量回升。
"""
import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from fastapi_app.services import finished_stock_service as fss
from fastapi_app.shared_models import DailyProductionRecord, Order, Product, StockOut, StockReturn

BATCH = '0464611101'
IN_QTY = 1000
SHIPPED_QTY = 50
RETURN_QTY = 50


@pytest.fixture(autouse=True)
async def _init_numbering_engine():
    """退货单号生成器走全局 AsyncSessionLocal，需先初始化引擎（同 sr_api 的做法）。"""
    from fastapi_app.core import database as _db_mod
    await _db_mod.ensure_engine_for_current_loop()
    yield


@pytest.fixture(autouse=True)
async def _rollback_writes(async_db_session):
    """把每个用例的写入裹进 savepoint，用例结束即回滚。

    async_db_session 是「提交模式」夹具（隔离靠 test_engine 的整库重置，那是 session 级），
    直接写会泄漏给同 session 内的后续测试文件（曾让 test_stock_return_api.test_list_empty
    假红）。

    必须显式 rollback：``async with session.begin_nested()`` 在正常退出时会
    **RELEASE SAVEPOINT**（即把写入并入外层事务，随后被 async_db_session 的 teardown
    commit 真正落库），并不回滚。已实测 savepoint 本身能隔离（另一连接读不到、
    rollback 后 0 行），所以这里只要保证退出语义是 rollback。
    """
    nested = await async_db_session.begin_nested()
    try:
        yield
    finally:
        await nested.rollback()


def _uniq(prefix: str) -> str:
    return f'{prefix}-{uuid.uuid4().hex[:8]}'


async def _setup(db, *, product_name: str, customer: str) -> Product:
    """造 产品 + 包装部入库(批次) + 订单 + 一条带批次的出货(50)。"""
    p = Product(name=product_name, barcode=_uniq('BC'), current_stock=0, initial_stock=0)
    db.add(p)
    await db.flush()

    db.add(DailyProductionRecord(
        department='packaging', product_id=p.id, product_name=p.name, barcode='',
        unit_price=0, quantity=IN_QTY, production_date=date(2026, 10, 15),
        batch_no=BATCH, customer_name=customer,
    ))
    db.add(Order(order_no=_uniq('ORD'), product_id=p.id, customer=customer,
                 quantity=IN_QTY, status='待备货', order_date=datetime.now(UTC)))
    await db.flush()

    db.add(StockOut(stockout_no=_uniq('SO'), product_id=p.id, quantity=SHIPPED_QTY,
                    returned_quantity=0, customer=customer, batch_no=BATCH,
                    stockout_date=datetime.now(UTC), stockin_id=None,
                    order_id=None))
    await db.flush()
    return p


async def _row(db, product_name: str) -> dict:
    """按产品名精确取该产品在成品库存里的那一行（服务端过滤，避开分页只回 1 行的干扰）。"""
    res = await fss.get_finished_stock_summary(db, product_search=product_name, per_page=200)
    rows = [r for r in res['data'] if r['product_name'] == product_name]
    assert len(rows) == 1, f'期望「{product_name}」恰有一行，实际 {len(rows)}'
    return rows[0]


@pytest.mark.integration
@pytest.mark.asyncio
class TestReturnRaisesBatchAvailable:
    """退货使成品库存该批次的「库存」回升，「批次入库」不变"""

    async def test_return_adds_fifty_to_available_only(self, async_db_session):
        db = async_db_session
        name = _uniq('大大产品')
        p = await _setup(db, product_name=name, customer='大大')

        # 退货前：入库 1000，库存 = 1000 − 50 = 950
        before = await _row(db, name)
        assert before['batch_in_qty'] == IN_QTY
        assert before['batch_available'] == IN_QTY - SHIPPED_QTY == 950

        # 对该批次的出货记录退货 50
        from fastapi_app.services import stock_return_service
        so = (await db.execute(
            select(StockOut).where(
                StockOut.product_id == p.id, StockOut.batch_no == BATCH)
        )).scalars().first()
        assert so is not None

        # 直接调 service（不用 db_transaction：它 commit 会把数据泄漏给同 session 的后续
        # 测试文件；async_db_session 在用例结束统一回滚，flust 即可在本事务内读回）。
        await stock_return_service.create_stockreturn_core(
            db, stockout_id=so.id, quantity=RETURN_QTY,
            return_date=datetime.now(UTC),
        )
        await db.flush()

        # 退货后：批次入库不变，库存 950 → 1000
        after = await _row(db, name)
        assert after['batch_in_qty'] == IN_QTY, '退货不得改变批次入库量'
        assert after['batch_available'] == IN_QTY, '库存应回升到 1000'

    async def test_cancel_return_reverts_available(self, async_db_session):
        """取消退货对称回退：库存 1000 → 950。"""
        db = async_db_session
        name = _uniq('大大产品')
        p = await _setup(db, product_name=name, customer='大大')

        from fastapi_app.services import stock_return_service

        so = (await db.execute(
            select(StockOut).where(
                StockOut.product_id == p.id, StockOut.batch_no == BATCH)
        )).scalars().first()

        # 同样不用 db_transaction（避免 commit 泄漏给后续测试文件）
        ret = await stock_return_service.create_stockreturn_core(
            db, stockout_id=so.id, quantity=RETURN_QTY,
            return_date=datetime.now(UTC))
        ret_id = ret.id
        await db.flush()

        mid = await _row(db, name)
        assert mid['batch_available'] == IN_QTY == 1000

        ret = (await db.execute(
            select(StockReturn).where(StockReturn.id == ret_id)
        )).scalars().one()

        await stock_return_service.cancel_stockreturn_core(db, ret)
        await db.flush()

        after = await _row(db, name)
        assert after['batch_in_qty'] == IN_QTY, '取消退货不得改变批次入库量'
        assert after['batch_available'] == 950, '取消后应回到退货前的 950'
