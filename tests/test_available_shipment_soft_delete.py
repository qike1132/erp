"""可出货量的软删除过滤回归（2026-09-28）

背景：``calculate_available_shipment_quantity`` 增加
``Order.is_deleted.isnot(True)`` 过滤，是为了修「删除订单后仍能按已删订单的数量
出货/抵扣」。但该函数在全部 11 个调用点都被 patch 掉，这行过滤此前没有任何测试。

本文件用真库锁定口径：软删除的订单不得计入可出货量。
"""
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fastapi_app.services.inventory_service import calculate_available_shipment_quantity
from fastapi_app.shared_models import Order, Product

pytestmark = pytest.mark.integration

CUSTOMER = '可出货量软删测试客户'


@pytest_asyncio.fixture
async def db(test_engine):
    """函数级会话 + 事务回滚隔离（复用会话级 test_engine）。"""
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False,
    )
    async with factory() as session:
        async with session.begin() as transaction:
            yield session
            await transaction.rollback()


async def test_soft_deleted_order_excluded_from_available_shipment(db):
    """软删除的订单不再计入可出货量（旧实现会继续按它出货）。"""
    product = Product(name='SAS-产品', barcode='SAS-P1', current_stock=0, initial_stock=0)
    db.add(product)
    await db.flush()

    order = Order(
        order_no='SAS-O-001', customer=CUSTOMER, order_date=datetime.now(UTC),
        product_id=product.id, quantity=100, order_type='regular', status='待备货',
    )
    db.add(order)
    await db.flush()

    before = await calculate_available_shipment_quantity(
        db, product.id, CUSTOMER, order_type='regular',
    )
    assert before['available_quantity'] == 100
    assert [o['order_no'] for o in before['orders']] == ['SAS-O-001']

    order.is_deleted = True
    await db.flush()

    after = await calculate_available_shipment_quantity(
        db, product.id, CUSTOMER, order_type='regular',
    )
    assert after['available_quantity'] == 0, '软删除订单仍被计入可出货量'
    assert after['order_quantity'] == 0
    assert after['orders'] == [], '软删除订单仍出现在可出货订单明细里'
