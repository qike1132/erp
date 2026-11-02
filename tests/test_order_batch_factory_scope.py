"""批次接口的工厂隔离回归。

订单写端点（order.py）早有 `_assert_order_factory_scoped`，而同样吃
`order_manage` 权限的批次四个端点从未校验工厂：厂绑定用户只要拿到自增
order_id，就能改批次号、批量分配、整批归档他厂订单，服务层也没有兜底过滤。

本文件用真实测试库跑服务层入口，覆盖三条写路径与一条放行对照。
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException

from fastapi_app.core.security import hash_password
from fastapi_app.services import order_batch_service
from fastapi_app.shared_models.order import Order
from fastapi_app.shared_models.order_item import OrderItem
from fastapi_app.shared_models.product import Product
from fastapi_app.shared_models.user import User


async def _make_user(db, factory: str) -> User:
    suffix = uuid4().hex[:8]
    user = User(
        username=f'factory-{suffix}',
        password=hash_password('x' * 12),
        is_super=False,
        status=True,
        factory=factory,
    )
    db.add(user)
    await db.flush()
    return user


async def _order_in_factory(db, customer_name: str, factory: str) -> Order:
    suffix = uuid4().hex[:10]
    product = Product(name=f'跨厂测试-{suffix}', barcode=f'XF-{suffix}', factory=factory)
    db.add(product)
    await db.flush()
    order = Order(
        order_no=f'ORD-XF-{suffix}',
        product_id=product.id,
        customer=customer_name,
        quantity=1,
        order_date=datetime.now(UTC),
        status='待备货',
    )
    db.add(order)
    await db.flush()
    # 工厂归属是从 order_item -> product.factory 推导的；没有明细行的订单
    # 对闸门不可见，因此必须建明细才能验证隔离真的生效。
    db.add(OrderItem(order_id=order.id, product_id=product.id, quantity=1))
    await db.flush()
    return order


async def test_update_batch_no_rejects_other_factory(async_db_session, test_customer):
    order = await _order_in_factory(async_db_session, test_customer.name, '湖北')
    user = await _make_user(async_db_session, '东莞')
    with pytest.raises(HTTPException) as ei:
        await order_batch_service.update_batch_no(
            async_db_session, order_id=order.id, batch_no='B-XF',
            sync_same_batch=False, user=user,
        )
    assert ei.value.status_code == 404


async def test_batch_assign_rejects_other_factory(async_db_session, test_customer):
    order = await _order_in_factory(async_db_session, test_customer.name, '湖北')
    user = await _make_user(async_db_session, '东莞')
    with pytest.raises(HTTPException) as ei:
        await order_batch_service.batch_assign(
            async_db_session, order_ids=[order.id], batch_no='B-XF', user=user,
        )
    assert ei.value.status_code == 404


async def test_complete_batch_rejects_other_factory(async_db_session, test_customer):
    order = await _order_in_factory(async_db_session, test_customer.name, '湖北')
    order.batch_no = f'B-XF-{uuid4().hex[:8]}'
    await async_db_session.flush()
    user = await _make_user(async_db_session, '东莞')
    with pytest.raises(HTTPException) as ei:
        await order_batch_service.complete_batch(
            async_db_session, batch_no=order.batch_no, user=user,
        )
    assert ei.value.status_code == 404


async def test_same_factory_still_allowed(async_db_session, test_customer):
    """对照组：本厂订单必须照常放行，避免闸门写成「一律拒绝」。"""
    order = await _order_in_factory(async_db_session, test_customer.name, '东莞')
    user = await _make_user(async_db_session, '东莞')
    await order_batch_service.update_batch_no(
        async_db_session, order_id=order.id, batch_no='B-OK',
        sync_same_batch=False, user=user,
    )
    await async_db_session.refresh(order)
    assert order.batch_no == 'B-OK'
