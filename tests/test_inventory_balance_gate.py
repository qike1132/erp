"""库存结余闸门（2026-10-07）口径一致性集成测试。

出货闸门 `stock_out_service._assert_inventory_balance` 复用
`stock_inventory_service.get_inventory_balance`；本文件锁定它与 /stock 页
`get_inventory_paginated` 的「库存（结余）」列**同口径**（包装部入库 − 已出货），
避免两处口径漂移。

复用根 conftest 的会话级 test_engine，只写测试库并事务回滚。
"""
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fastapi_app.services import stock_inventory_service as svc
from fastapi_app.shared_models import DailyProductionRecord, InventoryLog, Order, Product

pytestmark = pytest.mark.integration

CUSTOMER = '结余闸门口径客户'
PRODUCT_NAME = '结余闸门口径产品'
BARCODE = 'INV-BAL-001'


@pytest_asyncio.fixture
async def db(test_engine):
    """函数级会话：复用会话级引擎 + 事务回滚隔离。"""
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False,
    )
    async with factory() as session:
        async with session.begin() as transaction:
            yield session
            await transaction.rollback()


@pytest_asyncio.fixture
async def seeded(db):
    """包装部入库 100、已出货 30、一条订单（使 /stock 行存在）。"""
    product = Product(name=PRODUCT_NAME, barcode=BARCODE, current_stock=0, initial_stock=0)
    db.add(product)
    await db.flush()
    db.add(DailyProductionRecord(
        department='packaging', product_id=product.id,
        product_name=product.name, barcode=BARCODE,
        quantity=100, production_date=datetime.now(UTC).date(),
    ))
    db.add(InventoryLog(
        product_id=product.id, product_name=product.name, product_barcode=BARCODE,
        change_type='出库', change_quantity=-30,
    ))
    db.add(Order(
        order_no='INV-BAL-ORD-1', customer=CUSTOMER, product_id=product.id,
        quantity=50, order_date=datetime.now(UTC), status='待备货',
    ))
    await db.flush()
    return product


async def test_inventory_balance_is_packaging_minus_shipped(db, seeded):
    """get_inventory_balance = 包装部入库 − 已出货 = 100 − 30 = 70。"""
    assert await svc.get_inventory_balance(db, seeded.id) == 70


async def test_inventory_balance_matches_stock_page_column(db, seeded, monkeypatch):
    """与 /stock 页「库存」列同口径：两处数值必须相等。"""
    monkeypatch.setattr(svc, '_get_all_customers', svc._get_all_customers.__wrapped__)
    result = await svc.get_inventory_paginated.__wrapped__(
        db, search_customer=CUSTOMER, search_product=PRODUCT_NAME, page=1, per_page=50,
    )
    rows = [r for r in result['inventory_data'] if r['customer'] == CUSTOMER]
    assert rows, '库存页应包含该客户行'
    assert rows[0]['inventory_balance'] == await svc.get_inventory_balance(db, seeded.id)


async def test_inventory_balance_zero_when_never_packaged(db, monkeypatch):
    """从未包装入库的产品：结余为 0（闸门据此拒绝出货）。"""
    product = Product(name='未包装产品-结余', barcode='INV-BAL-002', current_stock=0, initial_stock=0)
    db.add(product)
    await db.flush()
    assert await svc.get_inventory_balance(db, product.id) == 0
