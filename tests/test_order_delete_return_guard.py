"""订单/出货删除 × 退货记录的交互（迁移 072 RESTRICT 的应用层出口）。

2026-10-08 用户实测：在退货流水里把退货取消后，出货流水仍删不掉
（「该出货存在关联的退货记录（含已取消）…无法删除」）。按决定改为：
删出货/订单时解除「已取消」退货对出货行的引用（退货行保留可追溯），
仍为 active 的退货继续拒绝删除。
"""
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from fastapi_app.services.order_utils import (
    assert_no_linked_returns,
    detach_cancelled_returns_for_order,
)
from fastapi_app.shared_models import StockOut, StockReturn


@pytest_asyncio.fixture
async def guard_rows_cleanup(async_db_session):
    """用例结束后清掉本文件造的行。

    共享测试库只在会话开始时整库重置，async_db_session 是提交模式——不清理会污染
    其它断言"空列表"的用例（如 test_stock_return_api.test_list_empty）。
    先删退货再删出货：active 退货仍引用出货行，反序会撞 RESTRICT 外键。
    """
    yield
    await async_db_session.execute(
        delete(StockReturn).where(StockReturn.return_no.like('SR-GUARD-%')))
    await async_db_session.execute(
        delete(StockOut).where(StockOut.stockout_no.like('SO-GUARD-%')))
    await async_db_session.commit()


async def _make_stockout(db, order, product, no: str) -> StockOut:
    stockout = StockOut(
        stockout_no=no, product_id=product.id, customer=order.customer,
        quantity=5, stockout_date=datetime.now(UTC), order_id=order.id,
    )
    db.add(stockout)
    await db.flush()
    return stockout


async def _make_return(db, stockout, order, status: str, no: str) -> StockReturn:
    stockreturn = StockReturn(
        return_no=no, product_id=stockout.product_id, quantity=1,
        stockout_id=stockout.id, order_id=order.id, status=status,
    )
    db.add(stockreturn)
    await db.flush()
    return stockreturn


class TestOrderDeleteReturnGuard:
    async def test_cancelled_return_does_not_block_and_detaches(
        self, async_db_session, test_order, test_product, guard_rows_cleanup,
    ):
        stockout = await _make_stockout(
            async_db_session, test_order, test_product, 'SO-GUARD-CXL')
        await _make_return(
            async_db_session, stockout, test_order, 'cancelled', 'SR-GUARD-CXL')

        # 已取消的退货不阻碍删除
        await assert_no_linked_returns(async_db_session, test_order.id)

        # 解除关联后：退货行仍在（可追溯），但 stockout_id 已置空
        await detach_cancelled_returns_for_order(async_db_session, test_order.id)
        await async_db_session.flush()
        stockreturn = (await async_db_session.execute(
            select(StockReturn).where(StockReturn.return_no == 'SR-GUARD-CXL')
        )).scalar_one()
        assert stockreturn.stockout_id is None

    async def test_active_return_blocks(self, async_db_session, test_order, test_product, guard_rows_cleanup):
        stockout = await _make_stockout(
            async_db_session, test_order, test_product, 'SO-GUARD-ACT')
        await _make_return(
            async_db_session, stockout, test_order, 'active', 'SR-GUARD-ACT')

        with pytest.raises(ValueError, match='退货记录'):
            await assert_no_linked_returns(async_db_session, test_order.id)

    async def test_delete_stockout_core_detaches_cancelled_return(
        self, async_db_session, test_order, test_product, guard_rows_cleanup,
    ):
        """删出货行时，已取消退货的 stockout_id 必须在本行 DELETE 之前解除。

        若解除与删除在同一次 flush 中顺序颠倒，RESTRICT 外键会抛 IntegrityError。
        """
        from fastapi_app.services.stock_out_service import delete_stockout_core
        stockout = await _make_stockout(
            async_db_session, test_order, test_product, 'SO-GUARD-DEL')
        await _make_return(
            async_db_session, stockout, test_order, 'cancelled', 'SR-GUARD-DEL')
        await async_db_session.commit()

        await delete_stockout_core(async_db_session, stockout)

        assert (await async_db_session.execute(
            select(StockOut).where(StockOut.id == stockout.id)
        )).scalar_one_or_none() is None
        stockreturn = (await async_db_session.execute(
            select(StockReturn).where(StockReturn.return_no == 'SR-GUARD-DEL')
        )).scalar_one()
        assert stockreturn.stockout_id is None
