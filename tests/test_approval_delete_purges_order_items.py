"""审批删除订单必须一并清掉 order_item（与直删路径同口径）。

背景（2026-10-08）：``approval_service._handle_delete_approval`` 软删订单时
未清理 order_item，而 ``order_item.product_id`` 是 FK NO ACTION —— 残留明细
会永久阻塞该产品的删除（与直删路径 ``order/commands.py::_purge_order_related_rows``
口径不一致）。生产 ``approval_request`` 表为空（该路径尚未被使用），属潜伏缺陷。
"""
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from fastapi_app.services.approval_service import approve_request
from fastapi_app.shared_models import (
    ApprovalLog,
    ApprovalRequest,
    Order,
    OrderItem,
    Product,
)

pytestmark = pytest.mark.integration

_ORDER_PREFIX = 'ADEL-O-'
_PRODUCT_BARCODE = 'ADEL-P1'


@pytest_asyncio.fixture
async def approval_delete_cleanup(async_db_session):
    """用例结束后清掉本文件造的行（共享测试库只在会话开始时整库重置）。"""
    yield
    order_ids = select(Order.id).where(Order.order_no.like(f'{_ORDER_PREFIX}%'))
    approval_ids = select(ApprovalRequest.id).where(ApprovalRequest.order_id.in_(order_ids))
    # 顺序：log → request → item → order → product（approval_log FK 是 NO ACTION）
    await async_db_session.execute(
        delete(ApprovalLog).where(ApprovalLog.approval_request_id.in_(approval_ids)))
    await async_db_session.execute(
        delete(ApprovalRequest).where(ApprovalRequest.order_id.in_(order_ids)))
    await async_db_session.execute(
        delete(OrderItem).where(OrderItem.order_id.in_(order_ids)))
    await async_db_session.execute(
        delete(Order).where(Order.order_no.like(f'{_ORDER_PREFIX}%')))
    await async_db_session.execute(
        delete(Product).where(Product.barcode == _PRODUCT_BARCODE))
    await async_db_session.commit()


class TestApprovalDeletePurgesOrderItems:
    async def test_approve_delete_removes_order_items(
        self, async_db_session, admin_user, normal_user, test_customer,
        approval_delete_cleanup,
    ):
        product = Product(
            name='ADEL 审批删除产品', barcode=_PRODUCT_BARCODE,
            current_stock=0, initial_stock=0,
        )
        async_db_session.add(product)
        await async_db_session.flush()

        order = Order(
            order_no=f'{_ORDER_PREFIX}001', customer=test_customer.name,
            order_date=datetime.now(UTC), product_id=product.id,
            quantity=1, status='待备货',
        )
        async_db_session.add(order)
        await async_db_session.flush()

        async_db_session.add(
            OrderItem(order_id=order.id, product_id=product.id, quantity=1))
        approval = ApprovalRequest(
            order_id=order.id, requester_id=normal_user.id,
            operation_type=ApprovalRequest.OPERATION_DELETE,
            status=ApprovalRequest.STATUS_PENDING,
        )
        async_db_session.add(approval)
        await async_db_session.flush()

        await approve_request(async_db_session, approval.id, admin_user)
        await async_db_session.flush()

        assert order.is_deleted is True, '订单应被软删除'
        leftover = (await async_db_session.execute(
            select(OrderItem.id).where(OrderItem.order_id == order.id)
        )).scalars().all()
        assert leftover == [], '审批删除后不得残留 order_item（否则永久阻塞产品删除）'
