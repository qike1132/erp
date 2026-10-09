"""审批管理服务层

提供审批列表查询、审批详情、同意/拒绝审批等核心业务逻辑。
审批操作通过行级锁（with_for_update）保证并发安全，
并通过状态机（can_transition）校验状态流转合法性。

TODO(multi-sku-order): 本模块多处读写 order.product_id/order.quantity
（审批同意/拒绝/撤销等逻辑）。多 SKU 模型下这些为首 item 兼容值，
完整改造涉及业务语义变更，风险高，待后续 spec 改造为遍历 order.items。
当前依赖 Task 3 设置的兼容值。
"""
import json
import logging
from collections.abc import Awaitable, Callable
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
from fastapi_app.services.order_utils import (
    assert_no_linked_returns,
    compute_order_status_from_db,
    detach_cancelled_returns_for_order,
    sync_single_item_quantity,
)
from fastapi_app.shared.stock_concurrency import assert_stock_available, get_product_for_update
from fastapi_app.shared_models import (
    ApprovalLog,
    ApprovalRequest,
    AuditLog,
    InventoryLog,
    Order,
    OrderItem,
    OrderStatusLog,
    OrderSyncRecord,
    StockOut,
    SyncRetryQueue,
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
    # 两种写法各被一条工具规则扇掉：dict 推导式触发 ruff C416（多余推导），
    # 而 dict(rows) 过不了 mypy —— SQLAlchemy 2.0 的 Row[tuple[K, V]] 不匹配
    # dict() 的 Iterable[tuple[_KT, _VT]] 重载。先落成显式 tuple 列表，两侧都干净。
    status_counts = [(status, count) for status, count in stats_result.all()]
    stats_dict = dict(status_counts)

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
            joinedload(ApprovalRequest.approver),
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

    # 注意：_handle_delete_approval 会删除该订单的其他 ApprovalRequest 记录（排除当前审批），
    # 当前审批保留以便设置状态和创建日志。
    handler = _OPERATION_HANDLERS.get(approval.operation_type)
    if handler is None:
        raise ValueError(f"不支持的操作类型：{approval.operation_type}")
    await handler(db, approval, order, current_user)
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
        raw_operation_data = approval.operation_data
        if raw_operation_data is None:
            raise TypeError('审批数据为空')
        operation_data = json.loads(raw_operation_data)
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
        product_id = order.product_id
        if product_id is None:
            raise ValueError(f'产品ID {product_id} 不存在')
        await get_product_for_update(db, product_id)

        db.add(InventoryLog(
            product_id=order.product_id,
            change_type='订单修改(审批)',
            change_quantity=stock_change,
            related_id=order.order_no,
            note=f'审批通过修改订单：{order.order_no}',
        ))

    order.customer = new_customer
    order.quantity = new_quantity
    # 明细数量必须跟随（列表页显示的是 order_item.quantity），与直改路径同源问题
    await sync_single_item_quantity(db, order.id, new_quantity)
    order.note = operation_data.get('note', order.note)
    order.is_locked = False
    order.locked_by_id = None
    # 数量变了 → order.status 是 (抵扣量, 出货量, 数量) 的派生值，必须重算。
    # 与 order/commands.py 的直改路径同源：两处原先都漏了这一步。
    order.status = await compute_order_status_from_db(db, order)


def _rollback_deduction_for_approval(
    db: AsyncSession, product, order: Order, order_stockouts: list, total_deducted: int,
) -> None:
    """回滚每条出库记录的净抵扣数量（产品已删除时无库存与日志目标可写，跳过）。"""
    if product is None:
        return
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
    # 负库存判定统一走 fastapi_app.shared.stock_concurrency 入口（P1-2b）
    assert_stock_available(
        product.current_stock, total_deducted,
        message=f'删除订单将导致库存为负数（当前库存：{product.current_stock}，净变化：{total_deducted:+d}）',
    )
    product.current_stock += total_deducted


def _add_delete_audit_log(
    db: AsyncSession, current_user: User, order: Order, approval_id: int, backup_path: str | None,
) -> None:
    """审批删订单的 AuditLog（与直删 _delete_order_directly 同口径，含备份路径）。"""
    db.add(AuditLog(
        user_id=current_user.id,
        username=current_user.username,
        action='DELETE',
        resource_type='order',
        resource_id=order.order_no,
        detail=json.dumps({
            'order_id': order.id,
            'order_no': order.order_no,
            'approval_id': approval_id,
            'backup_path': backup_path,
        }, ensure_ascii=False),
        status_code=200,
    ))


async def _handle_delete_approval(
    db: AsyncSession, approval: ApprovalRequest, order: Order, current_user: User,
) -> None:
    """处理删除类审批：回滚库存抵扣、清理关联记录、软删除订单。

    删除该订单的其他 ApprovalRequest 记录（排除当前审批），
    当前审批保留以便设置状态和创建日志。

    Args:
        db: 数据库会话。
        approval: 审批请求对象。
        order: 关联订单对象。
        current_user: 审批人（备份快照与 AuditLog 的操作者）。

    Raises:
        ValueError: 关联产品不存在或库存将变为负数时抛出。
    """
    # 退货记录存在时不可删除（迁移 072 RESTRICT 的应用层前置）：审批提交后才产生退货的
    # 场景下，直删入口的校验不会覆盖到这里，故此处再挡一次，给出明确原因而非 DB 层 409。
    await assert_no_linked_returns(db, order.id)

    # 产品删除后 order.product_id 会被置空（迁移 052：ON DELETE SET NULL）：
    # 此时无产品行可锁、无库存可回滚，且 inventory_log.product_id 是非空外键
    # （ON DELETE CASCADE），故跳过库存回滚，仅清理关联记录并软删除订单。
    product = (
        await get_product_for_update(db, order.product_id)
        if order.product_id is not None else None
    )

    result = await db.execute(
        select(StockOut).where(StockOut.order_id == order.id)
    )
    order_stockouts = list(result.scalars().all())
    total_deducted = sum(so.quantity - so.returned_quantity for so in order_stockouts)

    _rollback_deduction_for_approval(db, product, order, order_stockouts, total_deducted)

    # 先解除已取消退货对外键的引用（否则 RESTRICT 外键挡住下面的 stock_out 删除）；
    # active 退货已在 _handle_delete_approval 开头的 assert_no_linked_returns 处被拒。
    await detach_cancelled_returns_for_order(db, order.id)
    # 批量删除出库记录，避免逐条 ORM delete
    await db.execute(sa_delete(StockOut).where(StockOut.order_id == order.id))

    await db.execute(sa_delete(OrderSyncRecord).where(OrderSyncRecord.source_order_id == order.id))
    # 与直删路径同口径（Round16 B1/B2）：同步重试队列与状态日志随订单清理，
    # 否则 purchase_history 的状态日志仍指向已删订单（审计口径不一致）。
    # 备份与 AuditLog 对齐直删：审批删同样可追溯、可恢复。
    from fastapi_app.services.order.commands import (
        _collect_order_deletion_graph,
        _order_deletion_backup_payload,
        _write_order_deletion_backup,
    )
    backup_graph = await _collect_order_deletion_graph(db, order, order.id)
    backup_path = _write_order_deletion_backup(_order_deletion_backup_payload(
        order, order.id, current_user, backup_graph,
        len(backup_graph['status_logs']) + len(backup_graph['retry_records']),
    ))
    _add_delete_audit_log(db, current_user, order, approval.id, backup_path)
    await db.execute(sa_delete(SyncRetryQueue).where(SyncRetryQueue.source_order_id == order.id))
    await db.execute(sa_delete(OrderStatusLog).where(OrderStatusLog.order_no == order.order_no))
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

    # 清掉订单明细：与直删路径（order/commands.py::_purge_order_related_rows）同口径。
    # 明细的 product_id 是 FK NO ACTION，残留会永久阻塞该产品的删除；
    # outsource.order_item_id 为 CASCADE，随明细一并清理。
    await db.execute(sa_delete(OrderItem).where(OrderItem.order_id == order.id))

    # 级联清理该订单同步产生的采购计划明细（2026-10-06 删除联动，
    # 与 order_crud._delete_order_directly 同一口径）
    from fastapi_app.services.shipment_plan_sync import purge_shipment_plan_details_for_order
    await purge_shipment_plan_details_for_order(db, order.order_no)

    if product is not None:
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


# 审批操作类型 → handler 策略注册表（OCP）
# 新增操作类型时：新增 handler 函数并在此注册一行，approve_request 主流程无需改动。
_OPERATION_HANDLERS: dict[str, Callable[[AsyncSession, ApprovalRequest, Order, User], Awaitable[None]]] = {
    ApprovalRequest.OPERATION_EDIT: _handle_edit_approval,
    ApprovalRequest.OPERATION_DELETE: _handle_delete_approval,
}
