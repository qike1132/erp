"""审批管理服务层"""
import json
import logging
from datetime import datetime
from sqlalchemy import select, func, or_
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.shared_models import (
    ApprovalRequest, ApprovalLog, Order, Product, InventoryLog, StockOut, User
)
from fastapi_app.shared.stock_concurrency import get_product_for_update
from fastapi_app.services import escape_like

logger = logging.getLogger(__name__)


async def get_approval_list(db: AsyncSession, status_filter: str = 'pending', search: str = '',
                            page: int = 1, per_page: int = 20) -> dict:
    """获取审批列表（分页+搜索）"""
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

    # 获取总数
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # 分页
    per_page = min(per_page, 100)
    offset = (page - 1) * per_page
    query = query.order_by(ApprovalRequest.request_time.desc()).offset(offset).limit(per_page)
    result = await db.execute(query)
    approvals = list(result.unique().scalars().all())

    # 统计
    stats_result = await db.execute(
        select(ApprovalRequest.status, func.count(ApprovalRequest.id))
        .group_by(ApprovalRequest.status)
    )
    stats_dict = dict(stats_result.all())

    return {
        'approvals': [a.to_dict() for a in approvals],
        'total': total,
        'pages': (total + per_page - 1) // per_page if per_page > 0 else 0,
        'pending_count': stats_dict.get('pending', 0),
        'approved_count': stats_dict.get('approved', 0),
        'rejected_count': stats_dict.get('rejected', 0),
    }


async def get_approval_detail(db: AsyncSession, approval_id: int) -> dict:
    """获取审批详情"""
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


async def approve_request(db: AsyncSession, approval_id: int, current_user: User) -> str:
    """同意审批"""
    approval = await _get_pending_approval(db, approval_id, current_user)
    if not approval:
        raise ValueError("审批请求不存在或已处理")

    if approval.requester_id == current_user.id:
        raise ValueError("不能审批自己提交的申请")

    order = await db.get(Order, approval.order_id)
    if not order:
        raise ValueError("关联订单不存在")

    if approval.operation_type == 'edit':
        operation_data = json.loads(approval.operation_data)
        old_quantity = order.quantity
        new_quantity = operation_data.get('quantity', old_quantity)

        if new_quantity != old_quantity:
            product = await get_product_for_update(db, order.product_id)
            stock_change = new_quantity - old_quantity
            if product.current_stock + stock_change < 0:
                raise ValueError(f"库存不足，当前库存：{product.current_stock}")
            product.current_stock += stock_change

            log = InventoryLog(
                product_id=order.product_id,
                change_type='订单修改(审批)',
                change_quantity=stock_change,
                related_id=order.order_no,
                note=f'审批通过修改订单：{order.order_no}',
            )
            db.add(log)

        order.customer = operation_data.get('customer', order.customer)
        order.quantity = new_quantity
        order.note = operation_data.get('note', order.note)
        order.is_locked = False
        order.locked_by_id = None

    elif approval.operation_type == 'delete':
        product = await get_product_for_update(db, order.product_id)

        # 回滚抵扣
        result = await db.execute(
            select(StockOut).where(StockOut.order_id == order.id)
        )
        order_stockouts = list(result.scalars().all())
        total_deducted = sum(so.quantity for so in order_stockouts)

        for stockout in order_stockouts:
            rollback_log = InventoryLog(
                product_id=order.product_id,
                change_type='抵扣回滚(审批)',
                change_quantity=stockout.quantity,
                related_id=order.order_no,
                note=f'审批删除订单回滚抵扣',
            )
            db.add(rollback_log)

        product.current_stock -= order.quantity
        if total_deducted > 0:
            product.current_stock += total_deducted

        # 删除关联的 StockOut
        for stockout in order_stockouts:
            await db.delete(stockout)

        delete_log = InventoryLog(
            product_id=order.product_id,
            change_type='订单删除(审批)',
            change_quantity=-order.quantity,
            related_id=order.order_no,
            note=f'审批通过删除订单：{order.order_no}',
        )
        db.add(delete_log)

        await db.delete(order)

    approval.status = 'approved'
    approval.approver_id = current_user.id
    approval.approval_time = datetime.now()

    # 记录审批日志
    await _create_approval_log(db, approval, 'approve', current_user,
                                {'result': 'approved', 'operation': approval.operation_type})
    await _create_approval_log(db, approval, 'execute', current_user,
                                {'operation': approval.operation_type})

    await db.flush()
    return f'已同意{approval.operation_type_display}请求'


async def reject_request(db: AsyncSession, approval_id: int, current_user: User,
                         reason: str = '') -> str:
    """拒绝审批"""
    approval = await _get_pending_approval(db, approval_id, current_user)
    if not approval:
        raise ValueError("审批请求不存在或已处理")

    if approval.requester_id == current_user.id:
        raise ValueError("不能审批自己提交的申请")

    order = await db.get(Order, approval.order_id)
    if order:
        order.is_locked = False
        order.locked_by_id = None

    approval.status = 'rejected'
    approval.approver_id = current_user.id
    approval.approval_time = datetime.now()
    approval.rejection_reason = reason

    await _create_approval_log(db, approval, 'reject', current_user, {'reason': reason})

    await db.flush()
    return f'已拒绝{approval.operation_type_display}请求'


async def get_pending_count(db) -> int:
    """获取待审批数量"""
    result = await db.execute(
        select(func.count()).where(ApprovalRequest.status == 'pending')
    )
    return result.scalar() or 0


async def _get_pending_approval(db: AsyncSession, approval_id: int, current_user: User) -> ApprovalRequest | None:
    """获取待处理的审批请求"""
    approval = await db.get(ApprovalRequest, approval_id)
    if approval and approval.status != 'pending':
        raise ValueError("审批请求已处理，不能重复操作")
    return approval


async def _create_approval_log(db: AsyncSession, approval_request: ApprovalRequest, action: str,
                                actor: User, details: dict = None):
    """创建审批日志"""
    log = ApprovalLog(
        approval_request_id=approval_request.id,
        action=action,
        actor_id=actor.id,
        actor_name=actor.username,
        details=json.dumps(details, ensure_ascii=False) if details else None,
    )
    db.add(log)
