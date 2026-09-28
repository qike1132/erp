"""采购订单详情的损耗率字段回归（2026-09-28）

背景：``get_purchase_order`` 为「最终采购数量」的展示口径追加了订单级
``spare_rate`` 与明细级 ``loss_rate``（前端按「行内 loss_rate 优先，回退
订单级 spare_rate」回显）。全仓测试对 ``loss_rate`` 零命中 —— 后端漏发该字段
不会被任何用例发现，前端会静默回退。

本文件锁定该返回结构：订单级 spare_rate + 每条明细的 loss_rate 都必须下发。
"""
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fastapi_app.services.purchase_order_query import get_purchase_order
from fastapi_app.shared_models.purchase_order import PurchaseOrder, PurchaseOrderItem

pytestmark = pytest.mark.integration


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


async def test_purchase_order_detail_exposes_loss_rate_fields(db):
    """订单级 spare_rate 与明细级 loss_rate 必须随详情下发。"""
    order = PurchaseOrder(
        order_no='LR-PO-001', customer_name='损耗率测试客户',
        order_date=datetime.now(UTC).date(), status='pending', spare_rate=30,
    )
    db.add(order)
    await db.flush()
    db.add(PurchaseOrderItem(
        order_id=order.id, material_name='LR-布料', quantity=10, loss_rate=25,
    ))
    await db.flush()

    detail = await get_purchase_order(db, order.id)

    assert detail['spare_rate'] == 30.0
    assert [item['loss_rate'] for item in detail['items']] == [25.0]


async def test_purchase_order_detail_loss_rate_none_when_unset(db):
    """未配置时下发 None（而非缺字段），前端据此回退而不是取到 undefined。"""
    order = PurchaseOrder(
        order_no='LR-PO-002', customer_name='损耗率测试客户',
        order_date=datetime.now(UTC).date(), status='pending',
    )
    db.add(order)
    await db.flush()
    db.add(PurchaseOrderItem(order_id=order.id, material_name='LR-布料', quantity=10))
    await db.flush()

    detail = await get_purchase_order(db, order.id)

    assert detail['spare_rate'] is None
    assert 'loss_rate' in detail['items'][0]
    assert detail['items'][0]['loss_rate'] is None
