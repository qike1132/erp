"""审批管理服务层"""
import json
import logging
from datetime import UTC, datetime

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from fastapi_app.core.state_machine import (
    can_transition,
    get_allowed_actions,
)
from fastapi_app.services import escape_like
from fastapi_app.shared.stock_concurrency import get_product_for_update
from fastapi_app.shared_models import (
    ApprovalLog,
    ApprovalRequest,
    InventoryLog,
    Order,
    OrderSyncRecord,
    StockOut,
    User,
)

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def get_approval_list(db: AsyncSession, status_filter: str = 'pending', search: str = '',
                            page: int = 1, per_page: int = 20) -> dict:
    query = select(ApprovalRequest).options(
        joinedload(ApprovalRequest.order),
        joinedload(ApprovalRequest.requester),
        joinedload(ApprovalRequest.approver),
    )

    if status_filter and status_filter != 'all':
        query = query.where(ApprovalRequest.status == status_filter)

    if search:
        query = query.join(Order, ApprovalRequest.order_id == Order.id, isouter=True) \
                     .join(User, ApprovalRequest.requester_id == User.id) \
                     .where(
                         or_(
                             Order.order_no.like(f'%{escape_like(search)}%'),
                             User.username.like(f'%{escape_like(search)}%'),
                             ApprovalRequest.operation_type.like(f'%{escape_like(search)}%'),
                         )
                     )

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    per_page = min(per_page, 100)
    offset = (page - 1) * per_page
    query = query.order_by(ApprovalRequest.request_time.desc()).offset(offset).limit(per_page)
    result = await db.execute(query)
    approvals = list(result.unique().scalars().all())

    stats_result = await db.execute(
        select(ApprovalRequest.status, func.count(ApprovalRequest.id))
        .group_by(ApprovalRequest.status)
    )
    stats_dict = dict(stats_result.all())

    return {
        'approvals': [a.to_dict() for a in approvals],
        'total': total,
        'pages': (total + per_page - 1) // per_page if per_page > 0 else 0,
        'pending_count': stats_dict.get(ApprovalRequest.STATUS_PENDING, 0),
        'approved_count': stats_dict.get(ApprovalRequest.STATUS_APPROVED, 0),
        'rejected_count': stats_dict.get(ApprovalRequest.STATUS_REJECTED, 0),
    }


async def get_approval_detail(db: AsyncSession, approval_id: int) -> dict:
    result = await db.execute(
        select(ApprovalRequest)
        .options(
            selectinload(ApprovalRequest.logs),
            joinedload(ApprovalRequest.order).joinedload(Order.product),
            joinedload(ApprovalRequest.requester),
        )
        .where(ApprovalRequest.id == approval_id)
    )
    approval = result.unique().scalar_one_or_none()
    if not approval:
        raise ValueError("审批请求不存在")

    data = approval.to_dict()
    data['logs'] = [log.to_dict() for log in approval.logs]

    if approval.order:
        order = approval.order
        data['order_info'] = {
            'id': order.id,
            'order_no': order.order_no,
            'customer': order.customer,
            'quantity': order.quantity,
            'status': order.status,
            'product_name': order.product.name if order.product else '',
            'product_barcode': order.product.barcode if order.product else '',
            'note': order.note or '',
        }

    return data


async def approve_request(db: AsyncSession, approval_id: int, current_user: User) -> dict:
    """审批通过，返回包含操作详情的 dict 供 endpoint 层发布事件"""
    approval = await _get_pending_approval(db, approval_id)
    _validate_not_self_approval(approval, current_user)

    order = await db.get(Order, approval.order_id)
    if not order:
        raise ValueError("关联订单不存在")
    if order.is_deleted:
        raise ValueError("关联订单已被删除，无法审批")

    if approval.operation_type == ApprovalRequest.OPERATION_EDIT:
        await _handle_edit_approval(db, approval, order)
    elif approval.operation_type == ApprovalRequest.OPERATION_DELETE:
        await _handle_delete_approval(db, approval, order)
    else:
        raise ValueError(f"不支持的操作类型：{approval.operation_type}")

    # 注意：_handle_delete_approval 会删除该订单的所有 ApprovalRequest 记录（包括当前审批），
    # 但 SQLAlchemy 在 flush 之前不会使内存中的对象失效，因此 approval 对象仍可安全访问。
    approval.status = ApprovalRequest.STATUS_APPROVED
    approval.approver_id = current_user.id
    approval.approval_time = _utcnow()

    await _create_approval_log(db, approval, ApprovalLog.ACTION_APPROVE, current_user,
                                {'result': ApprovalRequest.STATUS_APPROVED, 'operation': approval.operation_type})
    await _create_approval_log(db, approval, ApprovalLog.ACTION_EXECUTE, current_user,
                                {'operation': approval.operation_type})

    await db.flush()

    return {
        'message': f'已同意{approval.operation_type_display}请求',
        'operation_type': approval.operation_type,
        'order_id': approval.order_id,
        'order_no': order.order_no if order else '',
    }


async def reject_request(db: AsyncSession, approval_id: int, current_user: User,
                         reason: str = '') -> str:
    approval = await _get_pending_approval(db, approval_id)
    _validate_not_self_approval(approval, current_user)

    order = await db.get(Order, approval.order_id)
    if order:
        order.is_locked = False
        order.locked_by_id = None

    approval.status = ApprovalRequest.STATUS_REJECTED
    approval.approver_id = current_user.id
    approval.approval_time = _utcnow()
    approval.rejection_reason = reason

    await _create_approval_log(db, approval, ApprovalLog.ACTION_REJECT, current_user, {'reason': reason})

    await db.flush()
    return f'已拒绝{approval.operation_type_display}请求'


async def get_pending_count(db: AsyncSession) -> int:
    result = await db.execute(
        select(func.count()).where(ApprovalRequest.status == ApprovalRequest.STATUS_PENDING)
    )
    return result.scalar() or 0


async def _get_pending_approval(db: AsyncSession, approval_id: int) -> ApprovalRequest:
    approval = await db.get(ApprovalRequest, approval_id)
    if not approval:
        raise ValueError("审批请求不存在或已处理")
    if not can_transition(approval.status, 'approve'):
        allowed = get_allowed_actions(approval.status)
        raise ValueError(
            f"审批请求状态异常：当前为'{approval.status}'，"
            f"只能执行以下操作：{allowed}"
        )
    return approval


def _validate_not_self_approval(approval: ApprovalRequest, current_user: User) -> None:
    if approval.requester_id == current_user.id:
        raise ValueError("不能审批自己提交的申请")


async def _handle_edit_approval(db: AsyncSession, approval: ApprovalRequest, order: Order) -> None:
    try:
        operation_data = json.loads(approval.operation_data)
    except (json.JSONDecodeError, TypeError) as e:
        raise ValueError(f"审批数据解析失败: {e}") from e

    old_quantity = order.quantity
    old_customer = order.customer
    new_quantity = operation_data.get('quantity', old_quantity)

    if new_quantity != old_quantity:
        product = await get_product_for_update(db, order.product_id)
        stock_change = new_quantity - old_quantity
        if product.current_stock + stock_change < 0:
            raise ValueError(f"库存不足，当前库存：{product.current_stock}")
        product.current_stock += stock_change

        db.add(InventoryLog(
            product_id=order.product_id,
            change_type='订单修改(审批)',
            change_quantity=stock_change,
            related_id=order.order_no,
            note=f'审批通过修改订单：{order.order_no}',
        ))

    order.customer = operation_data.get('customer', order.customer)
    order.quantity = new_quantity
    order.note = operation_data.get('note', order.note)
    order.is_locked = False
    order.locked_by_id = None

    # 同步更新采购中心中关联的采购订单
    new_customer = operation_data.get('customer', old_customer)
    try:
        from fastapi_app.services.order_purchase_sync import sync_order_update
        await sync_order_update(
            db, order.id,
            customer=new_customer, old_customer=old_customer,
            quantity=new_quantity, old_quantity=old_quantity,
        )
    except Exception as e:
        logger.warning('审批编辑-采购中心同步失败: %s', e)


async def _handle_delete_approval(db: AsyncSession, approval: ApprovalRequest, order: Order) -> None:
    product = await get_product_for_update(db, order.product_id)

    result = await db.execute(
        select(StockOut).where(StockOut.order_id == order.id)
    )
    order_stockouts = list(result.scalars().all())
    total_deducted = sum(so.quantity for so in order_stockouts)

    for stockout in order_stockouts:
        db.add(InventoryLog(
            product_id=order.product_id,
            change_type='抵扣回滚(审批)',
            change_quantity=stockout.quantity,
            related_id=order.order_no,
            note='审批删除订单回滚抵扣',
        ))

    product.current_stock -= order.quantity
    if total_deducted > 0:
        product.current_stock += total_deducted

    for stockout in order_stockouts:
        await db.delete(stockout)

    await db.execute(sa_delete(OrderSyncRecord).where(OrderSyncRecord.source_order_id == order.id))
    approval_result = await db.execute(
        select(ApprovalRequest.id).where(ApprovalRequest.order_id == order.id)
    )
    approval_ids = [row[0] for row in approval_result.all()]
    if approval_ids:
        await db.execute(sa_delete(ApprovalLog).where(ApprovalLog.approval_request_id.in_(approval_ids)))
    await db.execute(sa_delete(ApprovalRequest).where(ApprovalRequest.order_id == order.id))

    db.add(InventoryLog(
        product_id=order.product_id,
        change_type='订单删除(审批)',
        change_quantity=-order.quantity,
        related_id=order.order_no,
        note=f'审批通过删除订单：{order.order_no}',
    ))

    await db.delete(order)

    # 同步删除采购中心中关联的采购订单
    try:
        from fastapi_app.services.order_purchase_sync import sync_order_delete
        await sync_order_delete(db, order.id)
    except Exception as e:
        logger.warning('审批删除-采购中心同步失败: %s', e)


async def _create_approval_log(db: AsyncSession, approval_request: ApprovalRequest, action: str,
                                actor: User, details: dict | None = None):
    log = ApprovalLog(
        approval_request_id=approval_request.id,
        action=action,
        actor_id=actor.id,
        actor_name=actor.username,
        details=json.dumps(details, ensure_ascii=False) if details else None,
    )
    db.add(log)
