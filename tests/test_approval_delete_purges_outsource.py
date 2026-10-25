"""审批删除订单必须与直删路径同口径：清外发工序、解绑发货单（审计 M-3）。

背景（2026-10-25 上线前审计 M-3）：``approval_service._handle_delete_approval``
此前不调 ``_purge_outsource_processes``、不解绑 ``OutsourceShipment.order_id``。
OrderItem 的 CASCADE 只带走有明细的工序——``order_item_id IS NULL`` 的历史工序行
与发货单绑定残留，审批删单后出货计划仍挂已删订单号（直删路径
``order/commands.py::_purge_order_related_rows`` 一直有这两步）。
"""
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from fastapi_app.services.approval_service import approve_request
from fastapi_app.shared_models import (
    ApprovalLog,
    ApprovalRequest,
    InventoryLog,
    Order,
    OrderItem,
    Product,
)
from fastapi_app.shared_models.outsource import (
    OrderOutsourceProcess,
    OrderOutsourceProcessFlow,
    OutsourceShipment,
)

pytestmark = pytest.mark.integration

_ORDER_PREFIX = 'AOUT-O-'
_SHIP_PREFIX = 'AOUT-FH-'
_PRODUCT_BARCODE = 'AOUT-P1'


@pytest_asyncio.fixture
async def outsource_purge_cleanup(async_db_session):
    """用例结束后清掉本文件造的行（共享测试库只在会话开始时整库重置）。"""
    yield
    order_ids = select(Order.id).where(Order.order_no.like(f'{_ORDER_PREFIX}%'))
    approval_ids = select(ApprovalRequest.id).where(ApprovalRequest.order_id.in_(order_ids))
    # 顺序：flow → process → shipment → log → request → item → order → 产品流水 → 产品
    await async_db_session.execute(
        delete(OrderOutsourceProcessFlow).where(
            OrderOutsourceProcessFlow.process_id.in_(
                select(OrderOutsourceProcess.id).where(
                    OrderOutsourceProcess.order_id.in_(order_ids)))))
    await async_db_session.execute(
        delete(OrderOutsourceProcess).where(OrderOutsourceProcess.order_id.in_(order_ids)))
    await async_db_session.execute(
        delete(OutsourceShipment).where(OutsourceShipment.shipment_no.like(f'{_SHIP_PREFIX}%')))
    await async_db_session.execute(
        delete(ApprovalLog).where(ApprovalLog.approval_request_id.in_(approval_ids)))
    await async_db_session.execute(
        delete(ApprovalRequest).where(ApprovalRequest.order_id.in_(order_ids)))
    await async_db_session.execute(
        delete(OrderItem).where(OrderItem.order_id.in_(order_ids)))
    await async_db_session.execute(
        delete(Order).where(Order.order_no.like(f'{_ORDER_PREFIX}%')))
    product_ids = (await async_db_session.execute(
        select(Product.id).where(Product.barcode == _PRODUCT_BARCODE))).scalars().all()
    if product_ids:
        await async_db_session.execute(
            delete(InventoryLog).where(InventoryLog.product_id.in_(product_ids)))
    await async_db_session.execute(
        delete(Product).where(Product.barcode == _PRODUCT_BARCODE))
    await async_db_session.commit()


class TestApprovalDeletePurgesOutsource:
    async def test_approve_delete_purges_processes_and_unbinds_shipments(
        self, async_db_session, admin_user, normal_user, test_customer,
        outsource_purge_cleanup,
    ):
        product = Product(
            name='AOUT 审批删除产品', barcode=_PRODUCT_BARCODE,
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

        # order_item_id=NULL 的历史工序行：OrderItem 的 CASCADE 带不走它，
        # 只有显式 _purge_outsource_processes 才清得掉（本用例的靶点）。
        async_db_session.add(OrderOutsourceProcess(
            order_id=order.id, product_id=product.id,
            product_name=product.name, process_type='电绣',
            order_item_id=None, status='pending',
        ))
        async_db_session.add(OutsourceShipment(
            shipment_no=f'{_SHIP_PREFIX}001', order_id=order.id,
            customer=test_customer.name,
        ))
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
        leftover_processes = (await async_db_session.execute(
            select(OrderOutsourceProcess.id).where(OrderOutsourceProcess.order_id == order.id)
        )).scalars().all()
        assert leftover_processes == [], '审批删除后不得残留外发工序（含 order_item_id=NULL 的历史行）'
        bound = (await async_db_session.execute(
            select(OutsourceShipment.order_id).where(
                OutsourceShipment.shipment_no == f'{_SHIP_PREFIX}001')
        )).scalar_one_or_none()
        assert bound is None, '审批删除后发货单必须解绑 order_id（否则出货计划挂已删订单号）'
