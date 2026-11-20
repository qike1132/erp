"""available-stockins 的 `available` 净量口径回归（审计 data-H-1）。

/aux/available-stockins 返回的 `available`（可抵扣量）原先按毛量扣抵扣出货：
``s.quantity - sum(st.quantity)``，漏减抵扣行的部分退货（returned_quantity），
与备货列表「已抵扣」列（stock_inventory_service.py get_stockins 的 deducted
子查询）和备货导出 remaining（report_data_service.py）的净量口径分叉——
抵扣出货发生部分退货后，本端点报的可用量偏小，订单页抵扣提示
（useOrderForm 的 availableStock 求和）随之偏小，用户无法按真实可用量抵扣。

场景：备货 100 → 抵扣出货 40 → 该抵扣行部分退货 10 → 可用量应为
100 − (40 − 10) = 70（净量口径）；旧实现返回 60。
"""
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.shared_models import Product, StockIn, StockOut

pytestmark = pytest.mark.integration

CUSTOMER = '可用备货净量口径客户'


@pytest_asyncio.fixture
async def net_product(async_db_session):
    """每个用例独立产品（与根 conftest 的 test_product 同范式，不复用库存状态）。"""
    suffix = datetime.now(UTC).strftime('%H%M%S%f')
    p = Product(
        name=f'可用备货净量口径产品-{suffix}',
        barcode=f'AVAL-NET-{suffix}',
        current_stock=0,
        initial_stock=0,
    )
    async_db_session.add(p)
    await async_db_session.flush()
    return p


async def _seed_stockin(db: AsyncSession, product: Product, qty: int, no: str) -> StockIn:
    stockin = StockIn(
        stockin_no=no, product_id=product.id, customer=CUSTOMER,
        quantity=qty, stockin_date=datetime.now(UTC),
    )
    db.add(stockin)
    await db.flush()
    return stockin


async def test_available_subtracts_net_deduction(
    async_client, auth_headers, async_db_session, net_product,
):
    """备货100 → 抵扣40（部分退货10）→ available = 100 − (40−10) = 70。"""
    stockin = await _seed_stockin(async_db_session, net_product, 100, 'SI-AVAL-NET-1')
    async_db_session.add(StockOut(
        stockout_no='SO-AVAL-NET-1', product_id=net_product.id, customer=CUSTOMER,
        quantity=40, returned_quantity=10, stockin_id=stockin.id,
        stockout_date=datetime.now(UTC),
    ))
    await async_db_session.flush()

    resp = await async_client.get(
        '/api/v1/aux/available-stockins',
        params={'product_id': net_product.id},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    items = [i for i in resp.json() if i['id'] == stockin.id]
    assert items, '可用备货列表应包含该备货行'
    row = items[0]
    assert row['quantity'] == 100
    assert row['available'] == 70, (
        f'available 应为净量口径 100-(40-10)=70，实际 {row["available"]}'
    )


async def test_available_untouched_stockin_returns_full_quantity(
    async_client, auth_headers, async_db_session, net_product,
):
    """无抵扣行的备货 available 应等于 quantity（无 stockin_stockouts 分支不变）。"""
    stockin = await _seed_stockin(async_db_session, net_product, 55, 'SI-AVAL-NET-2')

    resp = await async_client.get(
        '/api/v1/aux/available-stockins',
        params={'product_id': net_product.id},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    items = [i for i in resp.json() if i['id'] == stockin.id]
    assert items and items[0]['available'] == 55
