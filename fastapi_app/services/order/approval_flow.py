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
from fastapi_app.core.cache_invalidation import (
    InvalidationStrategy,
    cache_mgr,
    schedule_post_commit_invalidation,
)
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
    # P2（2026-10-24）：提交前失效 + 提交后再失效一次（广覆盖 + 消竞态）。
    # 只做提交前失效时，窗口内的并发读会把旧列表回填并锁到 TTL；而只挂 post-commit
    # 又会让不经 db_transaction 提交的调用方彻底失去失效（见 schedule_post_commit_invalidation
    # 的 docstring），故两者并存。
    await cache_mgr.invalidate(
        InvalidationStrategy.DOMAIN, CacheDomain.ORDER | CacheDomain.REPORT)
    await cache_mgr.invalidate_dashboard()

    async def _invalidate_after_commit() -> None:
        await cache_mgr.invalidate(
            InvalidationStrategy.DOMAIN, CacheDomain.ORDER | CacheDomain.REPORT)
        await cache_mgr.invalidate_dashboard()

    schedule_post_commit_invalidation(db, _invalidate_after_commit)
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
    # 同 _submit_edit_approval：提交前失效 + 提交后再失效（P2，2026-10-24）
    await cache_mgr.invalidate(
        InvalidationStrategy.DOMAIN, CacheDomain.ORDER | CacheDomain.REPORT)
    await cache_mgr.invalidate_dashboard()

    async def _invalidate_after_commit() -> None:
        await cache_mgr.invalidate(
            InvalidationStrategy.DOMAIN, CacheDomain.ORDER | CacheDomain.REPORT)
        await cache_mgr.invalidate_dashboard()

    schedule_post_commit_invalidation(db, _invalidate_after_commit)
    logger.info(f'订单删除审批请求已提交：{order.order_no}，申请人：{current_user.username}')
    return {'success': True, 'message': '已提交删除审批请求，请等待管理员审批！', 'requires_approval': True}

async def cancel_approval(db: AsyncSession, approval_id: int, current_user: User) -> None:
    # 必须带行锁取审批行：approve_request / reject_request 都经 _get_pending_approval
    # 用 with_for_update() 锁住该行，唯独取消没有 —— 管理员「同意」与申请人「取消」并发时，
    # cancel 会在 approve 提交后覆盖状态为 cancelled，而订单编辑已落库、订单已解锁、
    # InventoryLog 已写入 → 用户以为取消成功，实际改动生效、审批台账与订单数据不一致。
    # 取锁后重新校验 can_transition，保证与 approve 串行。
    result = await db.execute(
        select(ApprovalRequest).where(ApprovalRequest.id == approval_id).with_for_update()
    )
    approval_request = result.scalar_one_or_none()
    if not approval_request:
        raise ValueError('审批请求不存在')

    if approval_request.requester_id != current_user.id and not current_user.is_super:
        raise PermissionDeniedError('您没有权限取消此审批请求')

    if not can_transition(approval_request.status, 'cancel'):
        raise ValueError(f'该审批请求当前状态为"{approval_request.status}"，无法取消')

    order = (await db.execute(
        select(Order).where(Order.id == approval_request.order_id)
        .with_for_update().execution_options(populate_existing=True)
    )).scalar_one_or_none()
    if order and not order.is_deleted:
        order.is_locked = False
        order.locked_by_id = None
        order.lock_time = None

    approval_request.status = ApprovalRequest.STATUS_CANCELLED

    await _create_approval_log_obj(approval_request, ApprovalLog.ACTION_CANCEL, current_user, {'reason': '用户主动取消'})

    await db.flush()

async def _check_order_lock(db: AsyncSession, order_id: int, order: Order,
                             current_user: User, action: str) -> None:
    # P1（2026-10-24）：审批中一律拒绝，与「锁主是不是自己」无关。
    # 原实现 `if not (order.is_locked and order.locked_by_id != current_user.id): return`
    # 在锁主就是申请人时直接早退 —— 而提交编辑/删除审批时锁主正是申请人本人，
    # 于是本人 pending 期间可直改明细/抵扣量，管理员批准时又按 operation_data 再改一次，
    # 数量被二次覆盖。update_order_item 的 docstring 明写「审批中的订单不可改」。
    #
    # 未锁定的订单不存在 pending 审批（提交审批时必然置 is_locked + locked_by_id），
    # 直接放行即可 —— 同时避免给每次编辑都加一次审批查询。
    if not order.is_locked:
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
    if order.locked_by_id != current_user.id:
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
