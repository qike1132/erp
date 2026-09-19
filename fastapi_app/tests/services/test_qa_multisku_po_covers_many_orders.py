"""QA 独立对抗：RC-2 回归——一张采购单覆盖多张客户订单时，单订单不得被高估。

真实数据形态：PO 20342（product_quantity=15）覆盖 15 张客户订单。
修复前每张订单都会被注入 MAX=15（系统性高估）；修复后每张订单 = 它自己的 SKU 数量。

仅 sqlite 内存库 + 真实模型；不接触生产库。
"""
from datetime import datetime

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from fastapi_app.services.order.beile import get_beile_orders_with_stockins
from fastapi_app.shared_models import (
    Base,
    MaterialRegistration,
    MaterialRegistrationItem,
    Order,
    OrderItem,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderSku,
    PurchaseOrderStatus,
    StockIn,
    User,
)

_TABLES = [
    User.__table__, Product.__table__, Order.__table__, OrderItem.__table__,
    StockIn.__table__, PurchaseOrder.__table__, PurchaseOrderItem.__table__,
    PurchaseOrderSku.__table__,
    MaterialRegistration.__table__, MaterialRegistrationItem.__table__,
]

_ORDER_IDS = list(range(64834, 64849))  # 15 张


@pytest_asyncio.fixture(autouse=True)
def _isolate_cache(monkeypatch):
    from fastapi_app.core import cache as cache_module
    monkeypatch.setattr(cache_module, '_get_redis_cache', lambda: None)
    cache_module.invalidate_local_cache('*')
    yield


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=_TABLES))
    maker = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def test_qa_po_covering_many_orders_no_overestimation(db):
    user = User(id=1, username='op', password='x', factory='湖北')
    pod = Product(id=1, name='企鹅', barcode='bP', factory='湖北')
    orders = [
        Order(id=oid, order_no=f'PO-{oid}', customer='stress-test',
              order_date=datetime(2026, 7, 20, 3, 7), product_id=1, quantity=1,
              items=[OrderItem(product_id=1, product_name='企鹅', product_barcode='bP', quantity=1)])
        for oid in _ORDER_IDS
    ]
    po = PurchaseOrder(id=20342, order_no='CG-20260720-0006', status=PurchaseOrderStatus.COMPLETED,
                       source_order_ids=str(_ORDER_IDS).replace(' ', ''),  # '[64834,...,64848]'
                       customer_name='stress-test', product_name='企鹅', product_quantity=15)
    skus = [
        PurchaseOrderSku(po_id=20342, product_name='企鹅', order_qty=1, spare_qty=0,
                         source_order_id=oid, source_record_type='order')
        for oid in _ORDER_IDS
    ]
    # 另加一张订单不被任何采购单覆盖，作为对照组
    unob = Order(id=99999, order_no='PO-99999', customer='另一客户',
                 order_date=datetime(2026, 7, 20, 3, 8), product_id=1, quantity=1,
                 items=[OrderItem(product_id=1, product_name='企鹅', product_barcode='bP', quantity=1)])

    db.add_all([user, pod, *orders, po, *skus, unob])
    await db.commit()

    result = await get_beile_orders_with_stockins(db, page=1, per_page=200)
    by_id = {r['id']: r for r in result['items'] if r['record_type'] == 'order'}

    bad = {oid: by_id[oid]['purchase_order_qty'] for oid in _ORDER_IDS
           if by_id[oid]['purchase_order_qty'] != 1}
    assert not bad, f'被 PO 合计(15)系统性高估的订单：{bad}'

    # 对照：未被覆盖的订单必须仍是未下单
    assert by_id[99999]['is_ordered'] is False

    # 逐 SKU 注入也必须是「自己的」数量
    for oid in _ORDER_IDS:
        it = by_id[oid]['items'][0]
        assert it['per_sku_source'] == 'po_sku'
        assert it['purchase_order_qty'] == 1
