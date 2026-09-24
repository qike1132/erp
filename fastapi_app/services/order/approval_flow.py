"""订单审批流（编辑/删除审批提交、取消、锁检查、审批日志）

自 order_crud.py 拆分（批次1-3），函数原文零改动。"""
# ruff: noqa: F401 - 拆分过渡期沿用完整导入块，待按模块收敛未用导入
import asyncio
import json
import logging
from datetime import UTC, datetime

from sqlalchemy import delete, func, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from fastapi_app.core.cache import CacheDomain, cache_result
from fastapi_app.core.cache_invalidation import InvalidationStrategy, cache_mgr
from fastapi_app.core.exception_handler import INFRA_EXCEPTIONS
from fastapi_app.core.exceptions import BusinessError, NotFoundError
from fastapi_app.core.state_machine import can_transition
from fastapi_app.core.validators import validate_not_empty, validate_quantity_range
from fastapi_app.services import escape_like
from fastapi_app.services.enhanced_pagination import (
    OFFSET_THRESHOLD,
    optimized_count,
)
from fastapi_app.services.notification_service import (
    StockEvent,
    dispatch_factory_notifications,
)
from fastapi_app.services.order._common import (
    PermissionDeniedError,
    _log_background_task_exception,
    _pending_tasks,
    _safe_invalidate_purchase_cache,
    _safe_publish_event,
)
from fastapi_app.services.order_utils import (
    _batch_deduct_quantities,
    compute_order_status_from_db,
)
from fastapi_app.services.serializers.order_serializer import (
    OrderSerializer,
)
from fastapi_app.shared.stock_concurrency import get_product_for_update
from fastapi_app.shared_models import (
    ApprovalLog,
    ApprovalRequest,
    InventoryLog,
    Notification,
    Order,
    OrderItem,
    OrderSyncRecord,
    Product,
    StockIn,
    StockOut,
    User,
)
from fastapi_app.shared_models.order import ORDER_STATUS_PENDING_STOCK

logger = logging.getLogger(__name__)





async def _submit_edit_approval(
    db: AsyncSession, order: Order, order_id: int,
    quantity: int, customer: str, note: str, current_user: User,
) -> dict:
    validate_not_empty(customer, "客户名称")
    if quantity is not None:
        validate_quantity_range(quantity, "订单数量")

    await _ensure_no_pending_request(db, order_id, current_user, '编辑')

    order.is_locked = True
    order.locked_by_id = current_user.id
    order.lock_time = datetime.now(UTC).replace(tzinfo=None)  # naive UTC: DB列类型为 TIMESTAMP WITHOUT TIME ZONE

    operation_data = {
        'customer': customer,
        'quantity': quantity,
        'note': note,
        'original_customer': order.customer,
        'original_quantity': order.quantity,
        'original_note': order.note or ''
    }

    approval_request = ApprovalRequest(
        order_id=order_id,
        requester_id=current_user.id,
        operation_type=ApprovalRequest.OPERATION_EDIT,
        operation_data=json.dumps(operation_data, ensure_ascii=False),
        status=ApprovalRequest.STATUS_PENDING,
        lock_time=datetime.now(UTC).replace(tzinfo=None)  # naive UTC: DB列类型为 TIMESTAMP WITHOUT TIME ZONE
    )
    db.add(approval_request)
    await db.flush()

    await _create_approval_log_obj(approval_request, ApprovalLog.ACTION_CREATE, current_user, {'operation_data': operation_data})

    await db.flush()
    await cache_mgr.invalidate(
        InvalidationStrategy.DOMAIN, CacheDomain.ORDER | CacheDomain.REPORT)
    await cache_mgr.invalidate_dashboard()
    logger.info(f'订单编辑审批请求已提交：{order.order_no}，申请人：{current_user.username}')
    return {'success': True, 'message': '已提交编辑审批请求，请等待管理员审批！', 'requires_approval': True}

async def _submit_delete_approval(
    db: AsyncSession, order: Order, order_id: int, current_user: User,
) -> dict:
    await _ensure_no_pending_request(db, order_id, current_user, '删除')

    order.is_locked = True
    order.locked_by_id = current_user.id
    order.lock_time = datetime.now(UTC).replace(tzinfo=None)  # naive UTC: DB列类型为 TIMESTAMP WITHOUT TIME ZONE

    operation_data = {
        'order_no': order.order_no,
        'customer': order.customer,
        'quantity': order.quantity,
        'product_name': order.product.name if order.product else '',
        'note': order.note or ''
    }

    approval_request = ApprovalRequest(
        order_id=order_id,
        requester_id=current_user.id,
        operation_type=ApprovalRequest.OPERATION_DELETE,
        operation_data=json.dumps(operation_data, ensure_ascii=False),
        status=ApprovalRequest.STATUS_PENDING,
        lock_time=datetime.now(UTC).replace(tzinfo=None)  # naive UTC: DB列类型为 TIMESTAMP WITHOUT TIME ZONE
    )
    db.add(approval_request)
    await db.flush()

    await _create_approval_log_obj(approval_request, ApprovalLog.ACTION_CREATE, current_user, {'operation_data': operation_data})

    await db.flush()
    await cache_mgr.invalidate(
        InvalidationStrategy.DOMAIN, CacheDomain.ORDER | CacheDomain.REPORT)
    await cache_mgr.invalidate_dashboard()
    logger.info(f'订单删除审批请求已提交：{order.order_no}，申请人：{current_user.username}')
    return {'success': True, 'message': '已提交删除审批请求，请等待管理员审批！', 'requires_approval': True}

async def cancel_approval(db: AsyncSession, approval_id: int, current_user: User) -> None:
    approval_request = await db.get(ApprovalRequest, approval_id)
    if not approval_request:
        raise ValueError('审批请求不存在')

    if approval_request.requester_id != current_user.id and not current_user.is_super:
        raise PermissionDeniedError('您没有权限取消此审批请求')

    if not can_transition(approval_request.status, 'cancel'):
        raise ValueError(f'该审批请求当前状态为"{approval_request.status}"，无法取消')

    order = await db.get(Order, approval_request.order_id)
    if order and not order.is_deleted:
        order.is_locked = False
        order.locked_by_id = None
        order.lock_time = None

    approval_request.status = ApprovalRequest.STATUS_CANCELLED

    await _create_approval_log_obj(approval_request, ApprovalLog.ACTION_CANCEL, current_user, {'reason': '用户主动取消'})

    await db.flush()

async def _check_order_lock(db: AsyncSession, order_id: int, order: Order,
                             current_user: User, action: str) -> None:
    if not (order.is_locked and order.locked_by_id != current_user.id):
        return
    result = await db.execute(
        select(ApprovalRequest).options(
            joinedload(ApprovalRequest.requester)
        ).where(
            ApprovalRequest.order_id == order_id,
            ApprovalRequest.status == ApprovalRequest.STATUS_PENDING,
        )
    )
    pending = result.unique().scalar_one_or_none()
    if pending:
        raise ValueError(f'该订单正在等待审批（申请人：{pending.requester.username}），暂时无法{action}！')
    raise ValueError(f'该订单已被其他用户锁定，暂时无法{action}！')

async def _ensure_no_pending_request(db: AsyncSession, order_id: int,
                                      current_user: User, action: str) -> None:
    result = await db.execute(
        select(ApprovalRequest).where(
            ApprovalRequest.order_id == order_id,
            ApprovalRequest.requester_id == current_user.id,
            ApprovalRequest.status == ApprovalRequest.STATUS_PENDING,
        )
    )
    if result.scalar_one_or_none():
        raise ValueError(f'您已提交过该订单的{action}审批请求，请等待管理员审批！')

async def _create_approval_log_obj(approval_request: ApprovalRequest, action: str,
                                    actor: User, details: dict | None = None) -> None:
    from sqlalchemy.orm import object_session

    from fastapi_app.services.approval_log_service import create_approval_log
    session = object_session(approval_request)
    if session:
        await create_approval_log(session, approval_request, action, actor, details)
