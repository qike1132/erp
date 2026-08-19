"""审批管理服务层

提供审批列表查询、审批详情、同意/拒绝审批等核心业务逻辑。
审批操作通过行级锁（with_for_update）保证并发安全，
并通过状态机（can_transition）校验状态流转合法性。

TODO(multi-sku-order): 本模块多处读写 order.product_id/order.quantity/order.order_type/
order.country（审批同意/拒绝/撤销等逻辑）。多 SKU 模型下这些为首 item 兼容值，
完整改造涉及业务语义变更，风险高，待后续 spec 改造为遍历 order.items。
当前依赖 Task 3 设置的兼容值。
"""
import json
import logging
from datetime import UTC, datetime

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from fastapi_app.core.sanitizer import escape_like
from fastapi_app.core.state_machine import (
    can_transition,
    get_allowed_actions,
)
from fastapi_app.core.validators import validate_not_empty, validate_quantity_range
from fastapi_app.services.approval_log_service import create_approval_log as _create_approval_log
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
from fastapi_app.utils import calc_total_pages

logger = logging.getLogger(__name__)

# 每页最大条数上限
_MAX_PER_PAGE = 100


def _utcnow() -> datetime:
    """返回当前 UTC 时间（naive，匹配 DB 列类型 TIMESTAMP WITHOUT TIME ZONE）。"""
    return datetime.now(UTC).replace(tzinfo=None)


async def get_approval_list(
    db: AsyncSession,
    status_filter: str = 'pending',
    search: str = '',
    page: int = 1,
    per_page: int = 20,
) -> dict:
    """查询审批列表（分页），返回审批数据及各状态计数。

    Args:
        db: 数据库会话。
        status_filter: 状态筛选，'all' 表示不筛选。
        search: 搜索关键词（订单号、用户名、操作类型）。
        page: 页码，从 1 开始。
        per_page: 每页条数，上限 100。

    Returns:
        包含 approvals/total/pages/pending_count/approved_count/rejected_count 的 dict。
    """
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

    per_page = min(per_page, _MAX_PER_PAGE)
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
        'pages': calc_total_pages(total, per_page),
        'pending_count': stats_dict.get(ApprovalRequest.STATUS_PENDING, 0),
        'approved_count': stats_dict.get(ApprovalRequest.STATUS_APPROVED, 0),
        'rejected_count': stats_dict.get(ApprovalRequest.STATUS_REJECTED, 0),
    }


async def get_approval_detail(db: AsyncSession, approval_id: int) -> dict:
    """获取审批详情，含操作日志和关联订单信息。

    Args:
        db: 数据库会话。
        approval_id: 审批请求 ID。

    Returns:
        审批详情 dict，包含 logs 和 order_info。

    Raises:
        ValueError: 审批请求不存在时抛出。
    """
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
    """审批通过，返回包含操作详情的 dict 供 endpoint 层发布事件。

    根据审批操作类型（编辑/删除）执行对应处理，更新审批状态并创建日志。

    Args:
        db: 数据库会话。
        approval_id: 审批请求 ID。
        current_user: 当前审批人。

    Returns:
        包含 message/operation_type/order_id/order_no 的 dict。

    Raises:
        ValueError: 审批请求不存在、状态异常、自审批、关联订单不存在等。
    """
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

    # 注意：_handle_delete_approval 会删除该订单的其他 ApprovalRequest 记录（排除当前审批），
    # 当前审批保留以便设置状态和创建日志。
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
    """拒绝审批请求，解除订单锁定并记录原因。

    Args:
        db: 数据库会话。
        approval_id: 审批请求 ID。
        current_user: 当前审批人。
        reason: 拒绝原因。

    Returns:
        操作结果消息字符串。

    Raises:
        ValueError: 审批请求不存在、状态异常、自审批时抛出。
    """
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
    """获取待处理审批数量。

    Args:
        db: 数据库会话。

    Returns:
        待处理审批数量。
    """
    result = await db.execute(
        select(func.count()).where(ApprovalRequest.status == ApprovalRequest.STATUS_PENDING)
    )
    return result.scalar() or 0


async def _get_pending_approval(db: AsyncSession, approval_id: int) -> ApprovalRequest:
    """获取待处理审批请求（带行级锁），校验状态机是否允许审批操作。

    Args:
        db: 数据库会话。
        approval_id: 审批请求 ID。

    Returns:
        ApprovalRequest ORM 对象。

    Raises:
        ValueError: 审批请求不存在或状态不允许审批时抛出。
    """
    result = await db.execute(
        select(ApprovalRequest).where(ApprovalRequest.id == approval_id).with_for_update()
    )
    approval = result.scalar_one_or_none()
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
    """校验不允许审批自己提交的申请。

    Args:
        approval: 审批请求对象。
        current_user: 当前审批人。

    Raises:
        ValueError: 审批人与申请人相同时抛出。
    """
    if approval.requester_id == current_user.id:
        raise ValueError("不能审批自己提交的申请")


async def _handle_edit_approval(db: AsyncSession, approval: ApprovalRequest, order: Order) -> None:
    """处理编辑类审批：应用订单修改并记录库存变更。

    Args:
        db: 数据库会话。
        approval: 审批请求对象（含 operation_data）。
        order: 关联订单对象。

    Raises:
        ValueError: 审批数据解析失败或校验不通过时抛出。
    """
    try:
        operation_data = json.loads(approval.operation_data)
    except (json.JSONDecodeError, TypeError) as e:
        raise ValueError(f"审批数据解析失败: {e}") from e

    # TODO(multi-sku-order): 读取/修改 order.quantity/product_id 在多 SKU 下语义变更，待后续 spec 改造为遍历 order.items；当前依赖兼容值。
    old_quantity = order.quantity
    old_customer = order.customer
    new_quantity = int(operation_data.get('quantity', old_quantity))
    new_customer = operation_data.get('customer', old_customer)

    validate_quantity_range(new_quantity, "订单数量")
    validate_not_empty(new_customer, "客户名称")

    if new_quantity != old_quantity:
        stock_change = new_quantity - old_quantity
        await get_product_for_update(db, order.product_id)

        db.add(InventoryLog(
            product_id=order.product_id,
            change_type='订单修改(审批)',
            change_quantity=stock_change,
            related_id=order.order_no,
            note=f'审批通过修改订单：{order.order_no}',
        ))

    order.customer = new_customer
    order.quantity = new_quantity
    order.note = operation_data.get('note', order.note)
    order.is_locked = False
    order.locked_by_id = None


async def _handle_delete_approval(db: AsyncSession, approval: ApprovalRequest, order: Order) -> None:
    """处理删除类审批：回滚库存抵扣、清理关联记录、软删除订单。

    删除该订单的其他 ApprovalRequest 记录（排除当前审批），
    当前审批保留以便设置状态和创建日志。

    Args:
        db: 数据库会话。
        approval: 审批请求对象。
        order: 关联订单对象。

    Raises:
        ValueError: 关联产品不存在或库存将变为负数时抛出。
    """
    product = await get_product_for_update(db, order.product_id)
    if not product:
        raise ValueError("关联产品不存在")

    result = await db.execute(
        select(StockOut).where(StockOut.order_id == order.id)
    )
    order_stockouts = list(result.scalars().all())
    total_deducted = sum(so.quantity - so.returned_quantity for so in order_stockouts)

    # 回滚每条出库记录的净抵扣数量
    for stockout in order_stockouts:
        net_qty = stockout.quantity - stockout.returned_quantity
        if net_qty <= 0:
            continue
        db.add(InventoryLog(
            product_id=order.product_id,
            change_type='抵扣回滚(审批)',
            change_quantity=net_qty,
            related_id=order.order_no,
            note=f'审批删除订单回滚抵扣，净退回{net_qty}件',
        ))

    net_change = total_deducted
    if product.current_stock + net_change < 0:
        raise ValueError(f'删除订单将导致库存为负数（当前库存：{product.current_stock}，净变化：{net_change:+d}）')
    product.current_stock += net_change

    # 批量删除出库记录，避免逐条 ORM delete
    await db.execute(sa_delete(StockOut).where(StockOut.order_id == order.id))

    await db.execute(sa_delete(OrderSyncRecord).where(OrderSyncRecord.source_order_id == order.id))
    approval_result = await db.execute(
        select(ApprovalRequest.id).where(
            ApprovalRequest.order_id == order.id,
            ApprovalRequest.id != approval.id,
        )
    )
    approval_ids = [row[0] for row in approval_result.all()]
    if approval_ids:
        await db.execute(sa_delete(ApprovalLog).where(ApprovalLog.approval_request_id.in_(approval_ids)))
    await db.execute(sa_delete(ApprovalRequest).where(
        ApprovalRequest.order_id == order.id,
        ApprovalRequest.id != approval.id,
    ))

    db.add(InventoryLog(
        product_id=order.product_id,
        change_type='订单删除(审批)',
        change_quantity=total_deducted,
        related_id=order.order_no,
        note=f'审批通过删除订单：{order.order_no}，抵扣回滚数量：{total_deducted}',
    ))

    # 软删除订单（与 order_crud._delete_order_directly 一致），
    # 避免硬删除触发 Order→ApprovalRequest 的 CASCADE，导致当前审批被级联删除
    # 而与新创建的 ApprovalLog 产生 FK NO ACTION 冲突。
    order.is_deleted = True
    order.deleted_at = _utcnow()
    order.deleted_by_id = approval.requester_id

    # 领域事件 ORDER_DELETED 已移至 endpoint 层（approval.py）事务提交后发布，
    # 订阅者使用独立 session，需可见已提交变更。
