"""QA 独立对抗：单 SKU 拆多供应商（4 张 completed 采购单）**不得被重复计数**。

最高优先级不变量（任务 §三.1）。工程师自测未覆盖本组合（他的 RC-2 用例是
「一张单覆盖多张订单」，多 SKU 用例是「单张单多 SKU」），故此处独立构造。

真实数据形态：订单 64997 有 4 张 completed 采购单（4 家供应商），每张
product_name='妹妹二代'、product_quantity=10000、source_order_ids=[64997]。
正确「订单数量」= 10000（去重），**不是 40000**。

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


async def test_qa_single_sku_four_suppliers_not_double_counted(db):
    user = User(id=1, username='op', password='x', factory='湖北')
    pod = Product(id=20533, name='妹妹二代', barcode='bMM2', factory='湖北')
    order = Order(
        id=64997, order_no='PO-20260804-0006', customer='MINISO国内',
        order_date=datetime(2026, 8, 4, 6, 14, 8), product_id=20533, quantity=10000,
        items=[OrderItem(product_id=20533, product_name='妹妹二代',
                         product_barcode='bMM2', quantity=10000)],
        confirmed_at=datetime(2026, 8, 4, 6, 14, 8),
    )
    # 4 家供应商各 1 张 completed 采购单，均只覆盖该订单，product_quantity=10000
    pos = [
        PurchaseOrder(id=20370 + i, order_no=f'CG-000{i}', status=PurchaseOrderStatus.COMPLETED,
                      supplier_name=f'供应商{i}', source_order_ids='[64997]',
                      customer_name='MINISO国内', product_name='妹妹二代',
                      product_quantity=10000)
        for i in range(4)
    ]
    skus = [
        PurchaseOrderSku(po_id=20370 + i, product_name='妹妹二代', order_qty=10000,
                         spare_qty=0, source_order_id=64997, source_record_type='order')
        for i in range(4)
    ]
    db.add_all([user, pod, order, *pos, *skus])
    await db.commit()

    result = await get_beile_orders_with_stockins(db, page=1, per_page=50)
    row = next(r for r in result['items'] if r['record_type'] == 'order' and r['id'] == 64997)

    # 核心断言：去重后 = 10000，不得为 40000
    assert row['purchase_order_qty'] == 10000, (
        f"单 SKU 拆 4 供应商被重复计数：得到 {row['purchase_order_qty']}，应为 10000"
    )
    assert row['is_ordered'] is True
    item = row['items'][0]
    assert item['per_sku_source'] == 'po_sku'
    assert item['purchase_order_qty'] == 10000, (
        f"逐 SKU 被重复计数：得到 {item['purchase_order_qty']}，应为 10000"
    )
