"""QA 独立对抗：迁移未执行（purchase_order_sku 缺失）时，/beile-list 必须优雅降级、绝不 500。

覆盖任务 §三.2 的「降级口径」与「生产库当前真实状态」：表缺失 → 逐 SKU 不可得 →
``per_sku_source='order_level'`` 且逐 SKU ``purchase_order_qty=None``（不得编造数字），
订单级回退既有 MAX 口径。

仅 sqlite 内存库 + 真实模型（**不含** PurchaseOrderSku 表）；不接触生产库。
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
    PurchaseOrderStatus,
    StockIn,
    User,
)

# 注意：故意不包含 PurchaseOrderSku.__table__
_TABLES = [
    User.__table__, Product.__table__, Order.__table__, OrderItem.__table__,
    StockIn.__table__, PurchaseOrder.__table__, PurchaseOrderItem.__table__,
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


async def test_qa_degrade_no_500_and_no_fabricated_per_sku(db):
    user = User(id=1, username='op', password='x', factory='湖北')
    pA = Product(id=1, name='A', barcode='bA', factory='湖北')
    pB = Product(id=2, name='B', barcode='bB', factory='湖北')
    order = Order(
        id=11, order_no='PO-011', customer='客户A', order_date=datetime(2026, 9, 1, 10, 0, 0),
        product_id=1, quantity=30000,
        items=[
            OrderItem(product_id=1, product_name='A', product_barcode='bA', quantity=10000),
            OrderItem(product_id=2, product_name='B', product_barcode='bB', quantity=20000),
        ],
    )
    po = PurchaseOrder(id=201, order_no='CPO-201', status=PurchaseOrderStatus.COMPLETED,
                       source_order_ids='[11]', customer_name='客户A', product_name='A、B',
                       product_quantity=30000)
    db.add_all([user, pA, pB, order, po])
    await db.commit()

    # 表缺失时不抛错（若抛错，本测试即失败）
    result = await get_beile_orders_with_stockins(db, page=1, per_page=50)
    row = next(r for r in result['items'] if r['record_type'] == 'order' and r['id'] == 11)

    assert row['is_ordered'] is True
    # 降级：订单级回退 MAX(product_quantity) 口径
    assert row['purchase_order_qty'] == 30000
    for it in row['items']:
        assert it['per_sku_source'] == 'order_level'
        assert it['purchase_order_qty'] is None, '降级时逐 SKU 不得编造数字'
        assert it['spare_quantity'] is None
