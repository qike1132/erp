"""
订单管理业务逻辑服务

从 Flask order.py 提取的核心业务逻辑，适配异步 SQLAlchemy。
"""
import asyncio
import json
import logging
from datetime import UTC, datetime

from sqlalchemy import delete, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from fastapi_app.core.cache import CacheDomain, cache_result, invalidate_related_caches
from fastapi_app.services.enhanced_pagination import OFFSET_THRESHOLD, optimized_count
from fastapi_app.core.state_machine import can_transition
from fastapi_app.services import escape_like
from fastapi_app.services.notification_service import StockEvent
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
from fastapi_app.shared_models.order import compute_status_from_stockouts

logger = logging.getLogger(__name__)


async def compute_order_status_from_db(db: AsyncSession, order: Order) -> str:
    """从数据库查询订单关联的出入库记录，派生计算订单状态"""
    # 复用 _batch_deduct_quantities 获取抵扣备货量（与列表展示逻辑一致）
    deduct_map = await _batch_deduct_quantities(db, [order.id])
    deducted_qty = max(0, deduct_map.get(order.id, 0))
    # 单独查询独立出货量（stockin_id IS NULL 的出库记录）
    result = await db.execute(
        select(func.coalesce(func.sum(StockOut.quantity - StockOut.returned_quantity), 0))
        .where(StockOut.order_id == order.id, StockOut.stockin_id.is_(None))
    )
    shipped_qty = max(0, int(result.scalar()))
    return compute_status_from_stockouts(order, deducted_qty, shipped_qty)


async def _safe_invalidate_purchase_cache():
    """安全清除采购中心缓存，失败仅记录警告"""
    try:
        from fastapi_app.core.purchase_cache import invalidate_purchase_caches
        await invalidate_purchase_caches()
    except (RuntimeError, OSError, ValueError):
        logger.warning("采购中心缓存失效失败", exc_info=True)


async def _safe_publish_event(event_type, data: dict, fcm_title: str = None, fcm_body: str = None):
    """安全发布库存事件（WebSocket + FCM），失败仅记录警告"""
    try:
        from fastapi_app.services.notification_service import publish_event_with_fcm
        await publish_event_with_fcm(event_type, data, fcm_title=fcm_title, fcm_body=fcm_body)
    except (RuntimeError, OSError, ValueError):
        logger.warning(f"事件发布失败: {event_type}", exc_info=True)


async def _batch_deduct_quantities(db: AsyncSession, order_ids: list[int]) -> dict[int, int]:
    """批量查询订单已抵扣备货数量（单次 SQL 聚合，替代 selectinload + Python 遍历）"""
    if not order_ids:
        return {}
    result = await db.execute(
        select(StockOut.order_id, func.coalesce(func.sum(StockOut.quantity - StockOut.returned_quantity), 0))
        .where(StockOut.order_id.in_(order_ids), StockOut.stockin_id.isnot(None))
        .group_by(StockOut.order_id)
    )
    return {row[0]: int(row[1]) for row in result.all()}


def _order_to_dict(o, deduct_quantity: int = 0) -> dict:
    """将 Order ORM 对象转换为前端字典，消除重复代码"""
    return {
        'id': o.id,
        'order_no': o.order_no,
        'customer': o.customer,
        'order_date': o.order_date.strftime('%Y-%m-%d %H:%M') if o.order_date else '',
        'product': {
            'id': o.product.id,
            'name': o.product.name,
            'barcode': o.product.barcode or '',
            'image': o.product.image or ''
        } if o.product else None,
        'quantity': o.quantity,
        'deduct_quantity': deduct_quantity,
        'status': o.status,
        'note': o.note or '',
        'order_type': o.order_type,
        'country': o.country or '',
        'is_locked': o.is_locked,
        'locked_by_name': o.locked_by.username if o.locked_by else None,
    }


class PermissionDeniedError(Exception):
    """用户无权限执行此操作"""
    pass


async def get_order_by_id(db: AsyncSession, order_id: int) -> dict | None:
    """根据ID获取单个订单详情（含关联数据）"""

    query = select(Order).options(
        joinedload(Order.product),
        joinedload(Order.locked_by)
    ).where(Order.id == order_id, Order.is_deleted.isnot(True))

    result = await db.execute(query)
    o = result.scalars().unique().first()
    if not o:
        return None

    deduct_map = await _batch_deduct_quantities(db, [o.id])
    return _order_to_dict(o, deduct_map.get(o.id, 0))


@cache_result(
    key_prefix="orders:list",
    ttl=60,
    local_ttl=15,
    key_builder=lambda *args, **kwargs: f"p{kwargs.get('page', 1)}:pp{kwargs.get('per_page', 50)}:c{kwargs.get('customer', '')}:pid{kwargs.get('product_id', '')}:s{kwargs.get('status', '')}:ot{kwargs.get('order_type', '')}",
)
async def get_orders(db: AsyncSession, page: int = 1, per_page: int = 50,
                     customer: str | None = None, product_id: int | None = None,
                     status: str | None = None, order_type: str | None = None) -> dict:
    """获取订单列表（含关联数据，支持分页和筛选）"""
    # 基础查询（移除 selectinload(order_stockouts)，改用 SQL 聚合）
    query = select(Order).options(
        joinedload(Order.product),
        joinedload(Order.locked_by)
    ).where(Order.is_deleted.isnot(True))
    count_query = select(func.count(Order.id)).where(Order.is_deleted.isnot(True))

    # 筛选条件（共用，避免 DRY 违反）
    conditions = []
    if customer:
        conditions.append(Order.customer.like(f'%{escape_like(customer)}%'))
    if product_id:
        conditions.append(Order.product_id == product_id)
    if status:
        conditions.append(Order.status == status)
    if order_type:
        conditions.append(Order.order_type == order_type)
    for c in conditions:
        query = query.where(c)
        count_query = count_query.where(c)

    # 总数 (use approximate count for large tables to avoid full scan)
    total = await optimized_count(db, count_query, table_name='order')

    # 分页查询 — 深翻页自动切换 keyset 分页
    offset = (page - 1) * per_page
    if offset > OFFSET_THRESHOLD:
        # 深翻页：用子查询定位游标值，避免 OFFSET 扫描跳过大量行
        logger.debug("深翻页 offset=%d 超过阈值 %d，自动使用keyset分页", offset, OFFSET_THRESHOLD)
        # 构造不含 eager load 的纯定位子查询（更快），使用 (order_date, id) 组合游标确保唯一性
        cursor_base = select(Order.order_date, Order.id).where(Order.is_deleted.isnot(True))
        for c in conditions:
            cursor_base = cursor_base.where(c)
        cursor_subq = cursor_base.order_by(Order.order_date.desc(), Order.id.desc()).offset(offset).limit(1).subquery()
        # 使用组合游标 (order_date, id) 做行比较，确保相同时间戳的行也能正确定位
        result = await db.execute(
            query.where(tuple_(Order.order_date, Order.id) <= select(cursor_subq.c.order_date, cursor_subq.c.id))
            .order_by(Order.order_date.desc(), Order.id.desc())
            .limit(per_page)
        )
        orders = result.scalars().unique().all()
        # fallback: 并发删除可能导致游标偏移，回退到 OFFSET
        if not orders:
            logger.debug("keyset分页返回空，fallback到OFFSET分页")
            result = await db.execute(
                query.order_by(Order.order_date.desc())
                .offset(offset)
                .limit(per_page)
            )
            orders = result.scalars().unique().all()
    else:
        # 常规翻页：OFFSET + LIMIT
        result = await db.execute(
            query.order_by(Order.order_date.desc())
            .offset(offset)
            .limit(per_page)
        )
        orders = result.scalars().unique().all()

    # 单次 SQL 聚合获取所有订单的抵扣数量，替代 selectinload + Python 遍历
    order_ids = [o.id for o in orders]
    deduct_map = await _batch_deduct_quantities(db, order_ids)

    orders_data = []
    for o in orders:
        orders_data.append(_order_to_dict(o, deduct_map.get(o.id, 0)))
    return {'items': orders_data, 'total': total, 'page': page, 'per_page': per_page}


async def create_order(db: AsyncSession, product_id: int, quantity: int,
                       customer: str, note: str, current_user: User,
                       order_type: str = 'regular', country: str | None = None) -> dict:
    """
    创建订单

    业务规则（与Flask一致）：
    - 产品必须存在
    - 数量 > 0 且 <= 9999999
    - 客户名称不能为空
    - 创建后增加产品库存
    - 定制订单必须填写国家名称
    """
    if order_type == 'custom' and not country:
        raise ValueError('定制订单必须填写国家名称')

    if quantity <= 0 or quantity > 9999999:
        raise ValueError('订单数量必须在1-9999999之间')

    product = await get_product_for_update(db, product_id)

    order_no = await _generate_order_number(db)

    order = Order(
        order_no=order_no,
        customer=customer,
        order_date=datetime.now(UTC).replace(tzinfo=None),
        product_id=product_id,
        quantity=quantity,
        note=note,
        status='待备货',
        order_type=order_type,
        country=country if order_type == 'custom' else None,
    )
    db.add(order)
    await db.flush()

    product.current_stock += quantity

    log = InventoryLog(
        product_id=product_id,
        change_type='订单',
        change_quantity=quantity,
        related_id=order_no,
        customer=customer,
        note=f'订单：{order_no}'
    )
    db.add(log)

    await db.flush()
    await db.refresh(order)
    await invalidate_related_caches(CacheDomain.ORDER)
    logger.info(f'订单添加成功：{order_no}，客户：{customer}，产品：{product.name}，数量：{quantity}')

    await _safe_invalidate_purchase_cache()

    # 发布订单创建事件，通知前端实时刷新
    await _safe_publish_event(StockEvent.ORDER_CREATED, {
            'order_id': order.id,
            'order_no': order_no,
            'customer': customer,
            'product_name': product.name,
            'quantity': quantity,
        }, fcm_title="新订单已创建", fcm_body=f"订单 {order_no}，客户：{customer}，数量：{quantity}")

    return order.to_dict()


async def update_order(db: AsyncSession, order_id: int, quantity: int,
                       customer: str, note: str, current_user: User,
                       order_type: str | None = None, country: str | None = None) -> dict:
    order = await db.get(Order, order_id)
    if not order or order.is_deleted:
        raise ValueError('订单不存在')

    await _check_order_lock(db, order_id, order, current_user, '编辑')

    if current_user.is_super:
        return await _update_order_directly(
            db, order, order_id, quantity, customer, note,
            current_user, order_type, country
        )
    else:
        return await _submit_edit_approval(
            db, order, order_id, quantity, customer, note, current_user
        )


async def _update_order_directly(
    db: AsyncSession, order: Order, order_id: int,
    quantity: int, customer: str, note: str,
    current_user: User, order_type: str | None,
    country: str | None,
) -> dict:
    if quantity <= 0 or quantity > 9999999:
        raise ValueError('订单数量必须在1-9999999之间')
    if not customer or not customer.strip():
        raise ValueError('客户名称不能为空')
    old_quantity = order.quantity
    _ = order.customer
    order.customer = customer
    order.quantity = quantity
    order.note = note
    if order_type is not None:
        order.order_type = order_type
    if country is not None:
        order.country = country if order_type != 'regular' else None

    if quantity != old_quantity:
        product = await get_product_for_update(db, order.product_id)
        product.current_stock += (quantity - old_quantity)
        log = InventoryLog(
            product_id=order.product_id,
            change_type='订单修改',
            change_quantity=quantity - old_quantity,
            related_id=order.order_no,
            note=f'订单修改：{order.order_no}'
        )
        db.add(log)

    await db.flush()
    await invalidate_related_caches(CacheDomain.ORDER)

    await _safe_invalidate_purchase_cache()

    logger.info(f'订单编辑成功：{order.order_no}，操作人：{current_user.username}')

    await _safe_publish_event(StockEvent.ORDER_UPDATED, {
        'order_id': order_id,
        'order_no': order.order_no,
        'customer': customer,
        'quantity': quantity,
    }, fcm_title="订单已更新", fcm_body=f"订单 {order.order_no} 信息已更新")

    return {'success': True, 'message': '订单编辑成功！', 'requires_approval': False}


async def _submit_edit_approval(
    db: AsyncSession, order: Order, order_id: int,
    quantity: int, customer: str, note: str, current_user: User,
) -> dict:
    if not customer or not customer.strip():
        raise ValueError('客户名称不能为空')
    if quantity is not None and (quantity <= 0 or quantity > 9999999):
        raise ValueError('订单数量必须在1-9999999之间')

    await _ensure_no_pending_request(db, order_id, current_user, '编辑')

    order.is_locked = True
    order.locked_by_id = current_user.id
    order.lock_time = datetime.now(UTC).replace(tzinfo=None)

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
        lock_time=datetime.now(UTC).replace(tzinfo=None)
    )
    db.add(approval_request)
    await db.flush()

    await _create_approval_log_obj(approval_request, ApprovalLog.ACTION_CREATE, current_user, {'operation_data': operation_data})

    await db.flush()
    await invalidate_related_caches(CacheDomain.ORDER)
    logger.info(f'订单编辑审批请求已提交：{order.order_no}，申请人：{current_user.username}')
    return {'success': True, 'message': '已提交编辑审批请求，请等待管理员审批！', 'requires_approval': True}


async def delete_order(db: AsyncSession, order_id: int, current_user: User) -> dict:
    order = await db.get(Order, order_id, options=[joinedload(Order.product)])
    if not order or order.is_deleted:
        raise ValueError('订单不存在')

    await _check_order_lock(db, order_id, order, current_user, '删除')

    if current_user.is_super:
        return await _delete_order_directly(db, order, order_id, current_user)
    else:
        return await _submit_delete_approval(db, order, order_id, current_user)


async def _delete_order_directly(
    db: AsyncSession, order: Order, order_id: int, current_user: User,
) -> dict:
    product = await get_product_for_update(db, order.product_id)

    result = await db.execute(
        select(StockOut).where(StockOut.order_id == order.id)
    )
    order_stockouts = result.scalars().all()
    total_deducted = sum(so.quantity - so.returned_quantity for so in order_stockouts)

    for stockout in order_stockouts:
        net_qty = stockout.quantity - stockout.returned_quantity
        if net_qty <= 0:
            continue
        stockout_log = InventoryLog(
            product_id=order.product_id,
            change_type='抵扣回滚',
            change_quantity=net_qty,
            related_id=order.order_no,
            note=f'订单删除回滚抵扣：{order.order_no}，恢复备货ID {stockout.stockin_id if stockout.stockin_id else "未知"} 的 {net_qty} 件'
        )
        db.add(stockout_log)

    net_change = total_deducted - order.quantity
    if product.current_stock + net_change < 0:
        raise ValueError(f'删除订单将导致库存为负数（产品：{product.name}，当前库存：{product.current_stock}，净变化：{net_change:+d}）')
    product.current_stock += net_change

    log = InventoryLog(
        product_id=order.product_id,
        change_type='订单删除',
        change_quantity=-order.quantity,
        related_id=order.order_no,
        note=f'订单删除：{order.order_no}，订单数量：{order.quantity}，抵扣回滚数量：{total_deducted}'
    )
    db.add(log)

    await db.execute(delete(StockOut).where(StockOut.order_id == order.id))
    await db.execute(delete(OrderSyncRecord).where(OrderSyncRecord.source_order_id == order_id))

    # 清理关联的 pending 采购订单
    from fastapi_app.services.purchase_order_service import cleanup_orphan_pending_purchase_orders
    await cleanup_orphan_pending_purchase_orders(db, [order_id])

    result = await db.execute(
        select(ApprovalRequest.id).where(ApprovalRequest.order_id == order_id)
    )
    approval_ids = [row[0] for row in result.all()]
    if approval_ids:
        await db.execute(delete(ApprovalLog).where(ApprovalLog.approval_request_id.in_(approval_ids)))
    await db.execute(delete(ApprovalRequest).where(ApprovalRequest.order_id == order_id))

    deleted_order_no = order.order_no
    order.is_deleted = True
    order.deleted_at = datetime.now(UTC).replace(tzinfo=None)
    order.deleted_by_id = current_user.id

    await db.flush()
    try:
        await invalidate_related_caches(CacheDomain.ORDER)
    except (OSError, ValueError) as e:
        logger.warning(f'缓存清除失败：{e}')

    await _safe_invalidate_purchase_cache()

    task = asyncio.create_task(_safe_publish_event(StockEvent.ORDER_DELETED, {
        'order_id': order_id,
        'order_no': deleted_order_no,
    }, fcm_title="订单已删除", fcm_body=f"订单 {deleted_order_no} 已被删除"))
    task.add_done_callback(lambda t: t.exception() and logger.error(f'订单删除事件发布失败: {t.exception()}') if not t.cancelled() and t.exception() else None)

    logger.info(f'订单删除成功：{deleted_order_no}，操作人：{current_user.username}，抵扣回滚：{total_deducted}')
    return {'success': True, 'message': f'订单删除成功！抵扣回滚数量：{total_deducted}', 'requires_approval': False}


async def _submit_delete_approval(
    db: AsyncSession, order: Order, order_id: int, current_user: User,
) -> dict:
    await _ensure_no_pending_request(db, order_id, current_user, '删除')

    order.is_locked = True
    order.locked_by_id = current_user.id
    order.lock_time = datetime.now(UTC).replace(tzinfo=None)

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
        lock_time=datetime.now(UTC).replace(tzinfo=None)
    )
    db.add(approval_request)
    await db.flush()

    await _create_approval_log_obj(approval_request, ApprovalLog.ACTION_CREATE, current_user, {'operation_data': operation_data})

    await db.flush()
    await invalidate_related_caches(CacheDomain.ORDER)
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


async def get_my_approvals(db: AsyncSession, current_user: User) -> list[dict]:
    """获取我的审批请求"""
    result = await db.execute(
        select(ApprovalRequest)
        .options(joinedload(ApprovalRequest.order), joinedload(ApprovalRequest.requester))
        .where(ApprovalRequest.requester_id == current_user.id)
        .order_by(ApprovalRequest.request_time.desc())
    )
    approvals = result.scalars().unique().all()
    return [a.to_dict() for a in approvals]


# ==================== 内部辅助函数 ====================

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


async def _generate_order_number(db: AsyncSession) -> str:
    from fastapi_app.services.batch_service import generate_order_number
    return await generate_order_number(db)


async def _create_approval_log_obj(approval_request: ApprovalRequest, action: str,
                                    actor: User, details: dict | None = None) -> None:
    from sqlalchemy.orm import object_session

    from fastapi_app.services.approval_service import _create_approval_log
    session = object_session(approval_request)
    if session:
        await _create_approval_log(session, approval_request, action, actor, details)


class _SavepointRollbackSignal(Exception):
    """批量处理单项业务校验失败，用于触发 savepoint 回滚但不作为真实错误"""


async def batch_create_orders(db: AsyncSession, orders_data: list) -> dict:
    """批量创建订单

    注意：同步至采购中心的操作不在此函数内执行，由调用方在事务提交后统一处理，
    以确保同步线程池中的独立 Session 能读取到已提交的订单数据。
    """
    from fastapi_app.services.batch_service import generate_order_number

    results = []
    created_order_ids = []  # 记录成功创建的订单ID，用于同步采购中心
    for order_data in orders_data:
        try:
            async with db.begin_nested():
                try:
                    product_id = int(order_data['product_id'])
                except (TypeError, ValueError, KeyError):
                    results.append({
                        'success': False, 'error': '无效的产品ID',
                        'order_no': order_data.get('order_no', '未知')
                    })
                    raise _SavepointRollbackSignal()
                try:
                    quantity = int(order_data.get('quantity', 0))
                except (TypeError, ValueError):
                    results.append({
                        'success': False, 'error': '无效的订单数量',
                        'order_no': order_data.get('order_no', '未知')
                    })
                    raise _SavepointRollbackSignal()
                customer = str(order_data.get('customer', '')).strip()

                if not product_id or not customer or quantity <= 0:
                    results.append({
                        'success': False, 'error': '缺少必填字段',
                        'order_no': order_data.get('order_no', '未知')
                    })
                    raise _SavepointRollbackSignal()

                if quantity > 9999999:
                    results.append({
                        'success': False, 'error': '订单数量必须在1-9999999之间',
                        'order_no': order_data.get('order_no', '未知')
                    })
                    raise _SavepointRollbackSignal()

                product = await get_product_for_update(db, product_id)

                order_no = await generate_order_number(db)

                order = Order(
                    order_no=order_no,
                    product_id=product_id,
                    customer=customer,
                    quantity=int(quantity),
                    order_date=datetime.now(UTC).replace(tzinfo=None),
                    status='待备货',
                    note=order_data.get('note', ''),
                    order_type=order_data.get('order_type', 'regular'),
                    country=order_data.get('country') if order_data.get('order_type') == 'custom' else None,
                )
                db.add(order)
                await db.flush()

                product.current_stock += int(quantity)

                log = InventoryLog(
                    product_id=product_id,
                    change_type='订单创建',
                    change_quantity=int(quantity),
                    change_date=datetime.now(UTC).replace(tzinfo=None),
                    customer=customer,
                    related_id=str(order.id),
                    note=f'批量创建订单 {order.order_no}',
                )
                db.add(log)

                # 处理抵扣备货
                deduct_stock = bool(order_data.get('deduct_stock'))
                deduct_quantity = int(order_data.get('deduct_quantity', 0) or 0)
                if deduct_stock and deduct_quantity > 0:
                    try:
                        from fastapi_app.services.batch_service import process_order_deduction
                        await process_order_deduction(
                            db, order, product_id, int(quantity),
                            deduct_stock=True,
                            custom_deduct_quantity=deduct_quantity,
                            product=product,
                        )
                    except (ValueError, TypeError, RuntimeError, OSError) as ded_err:
                        logger.error(f"订单抵扣处理失败: {ded_err}", exc_info=True)
                        results.append({
                            'success': False, 'error': '抵扣处理失败，请稍后重试',
                            'order_no': order.order_no,
                        })
                        raise _SavepointRollbackSignal() from ded_err

                results.append({
                    'success': True, 'order_no': order.order_no, 'id': order.id
                })
                created_order_ids.append(order.id)
        except _SavepointRollbackSignal:
            pass  # 业务校验失败，savepoint 已自动回滚，继续下一项
        except (ValueError, TypeError, OSError) as e:
            # 数据库异常，begin_nested 已自动回滚 savepoint，session 恢复有效状态
            logger.error(f"批量订单单项失败: {e}", exc_info=True)
            results.append({
                'success': False, 'error': str(e) or '订单处理失败，请稍后重试',
                'order_no': order_data.get('order_no', '未知')
            })

    return {'success': True, 'results': results, 'created_order_ids': created_order_ids}
