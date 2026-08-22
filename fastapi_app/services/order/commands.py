"""订单命令（创建/编辑/删除及直接执行路径、编号生成）

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



from fastapi_app.services.order.approval_flow import (
    _check_order_lock,
    _ensure_no_pending_request,
    _submit_delete_approval,
    _submit_edit_approval,
)



async def create_order(db: AsyncSession, product_id: int, quantity: int,
                       customer: str, note: str, current_user: User,
                       order_type: str = 'regular', country: str | None = None) -> dict:
    """
    创建订单

    业务规则：
    - 产品必须存在
    - 数量 > 0 且 <= 9999999
    - 客户名称不能为空
    - 创建订单记录及库存日志（不影响物理库存）
    - 定制订单必须填写国家名称
    """
    if order_type == 'custom' and not country:
        raise ValueError('定制订单必须填写国家名称')

    validate_quantity_range(quantity, "订单数量")

    product = await get_product_for_update(db, product_id)

    order_no = await _generate_order_number(db)

    async with db.begin_nested():
        order = Order(
            order_no=order_no,
            customer=customer,
            order_date=datetime.now(UTC).replace(tzinfo=None),  # naive UTC: DB列类型为 TIMESTAMP WITHOUT TIME ZONE
            product_id=product_id,
            quantity=quantity,
            note=note,
            status=ORDER_STATUS_PENDING_STOCK,
            order_type=order_type,
            country=country if order_type == 'custom' else None,
        )
        db.add(order)
        await db.flush()

        # 写入 OrderItem 明细（与兼容值 product_id/quantity 一致）：与批量创建路径对齐，
        # 保证所有订单都有 SKU 级明细，读取方后续可迁移为遍历 order.items。
        order_item = OrderItem(
            order_id=order.id,
            product_id=product_id,
            product_name=product.name,
            product_barcode=getattr(product, 'barcode', None),
            quantity=quantity,
            order_type=order_type,
            country=country if order_type == 'custom' else None,
            note=note,
        )
        db.add(order_item)

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

    # 返单自动带出外发工序：根据 SKU 预设生成湖北外发工序（失败不影响订单创建）
    from fastapi_app.services.outsource_service import auto_generate_for_order
    await auto_generate_for_order(db, order)

    await cache_mgr.invalidate(InvalidationStrategy.DOMAIN, CacheDomain.ORDER)
    # dashboard 缓存失效已移至 endpoint 层（事务提交后），此处不再重复
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
    result = await db.execute(select(Order).where(Order.id == order_id).with_for_update())
    order = result.scalar_one_or_none()
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
    validate_quantity_range(quantity, "订单数量")
    validate_not_empty(customer, "客户名称")
    # TODO(multi-sku-order): 读取/修改 order.quantity 在多 SKU 下语义变更（多 item 改哪个？），待后续 spec 改造为遍历 order.items；当前依赖兼容值。
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
        # TODO(multi-sku-order): order.product_id 在多 SKU 下为首 item 兼容值，库存调整需按 OrderItem 维度；待后续 spec 改造。
        await get_product_for_update(db, order.product_id)
        log = InventoryLog(
            product_id=order.product_id,
            change_type='订单修改',
            change_quantity=quantity - old_quantity,
            related_id=order.order_no,
            note=f'订单修改：{order.order_no}'
        )
        db.add(log)

    await db.flush()

    # Task 3.2: 派发工厂通知（order_updated）
    # 仅 flush 不 commit，与 _update_order_directly 事务模型一致；
    # 简单实现：传 changed_items=None，让 dispatch 遍历 order.items（内部 await 查询）。
    # 通知失败不应影响订单修改，捕获异常仅记录日志。
    try:
        await dispatch_factory_notifications(db, order, 'order_updated', None)
    except Exception as notify_err:  # broad-except: 服务层容错，记录异常并返回安全默认值
        logger.warning(
            "工厂通知派发失败 order_no=%s: %s", order.order_no, notify_err,
            exc_info=True,
        )

    await cache_mgr.invalidate(InvalidationStrategy.DOMAIN, CacheDomain.ORDER_AND_INVENTORY)
    # dashboard 缓存失效已移至 endpoint 层（事务提交后）

    await _safe_invalidate_purchase_cache()

    logger.info(f'订单编辑成功：{order.order_no}，操作人：{current_user.username}')

    await _safe_publish_event(StockEvent.ORDER_UPDATED, {
        'order_id': order_id,
        'order_no': order.order_no,
        'customer': customer,
        'quantity': quantity,
    }, fcm_title="订单已更新", fcm_body=f"订单 {order.order_no} 信息已更新")

    return {'success': True, 'message': '订单编辑成功！', 'requires_approval': False}

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

    # 批量构建抵扣回滚日志，消除循环内逐条 add 的 N+1 开销
    rollback_logs = []
    for stockout in order_stockouts:
        net_qty = stockout.quantity - stockout.returned_quantity
        if net_qty <= 0:
            continue
        rollback_logs.append(InventoryLog(
            product_id=order.product_id,
            change_type='抵扣回滚',
            change_quantity=net_qty,
            related_id=order.order_no,
            note=f'订单删除回滚抵扣：{order.order_no}，恢复备货ID {stockout.stockin_id if stockout.stockin_id else "未知"} 的 {net_qty} 件'
        ))
    if rollback_logs:
        db.add_all(rollback_logs)

    net_change = total_deducted
    if product.current_stock + net_change < 0:
        raise ValueError(f'删除订单将导致库存为负数（产品：{product.name}，当前库存：{product.current_stock}，净变化：{net_change:+d}）')
    product.current_stock += net_change

    log = InventoryLog(
        product_id=order.product_id,
        change_type='订单删除',
        change_quantity=total_deducted,
        related_id=order.order_no,
        note=f'订单删除：{order.order_no}，订单数量：{order.quantity}，抵扣回滚数量：{total_deducted}'
    )
    db.add(log)

    await db.execute(delete(StockOut).where(StockOut.order_id == order.id))
    await db.execute(delete(OrderSyncRecord).where(OrderSyncRecord.source_order_id == order_id))

    result = await db.execute(
        select(ApprovalRequest.id).where(ApprovalRequest.order_id == order_id)
    )
    approval_ids = [row[0] for row in result.all()]
    if approval_ids:
        await db.execute(delete(ApprovalLog).where(ApprovalLog.approval_request_id.in_(approval_ids)))
    await db.execute(delete(ApprovalRequest).where(ApprovalRequest.order_id == order_id))

    deleted_order_no = order.order_no
    order.is_deleted = True
    order.deleted_at = datetime.now(UTC).replace(tzinfo=None)  # naive UTC: DB列类型为 TIMESTAMP WITHOUT TIME ZONE
    order.deleted_by_id = current_user.id

    await db.flush()
    try:
        await cache_mgr.invalidate(InvalidationStrategy.DOMAIN, CacheDomain.ORDER)
        # dashboard 缓存失效已移至 endpoint 层（事务提交后）
    except INFRA_EXCEPTIONS as e:
        logger.warning('缓存清除失败: %s', e)

    await _safe_invalidate_purchase_cache()

    # StockEvent.ORDER_DELETED：仅 WebSocket/FCM 通知（不查询数据库，可在提交前调度）
    # 领域事件 ORDER_DELETED 由 endpoint 层在事务提交后直接发布（order.py）
    task = asyncio.create_task(_safe_publish_event(StockEvent.ORDER_DELETED, {
        'order_id': order_id,
        'order_no': deleted_order_no,
    }, fcm_title="订单已删除", fcm_body=f"订单 {deleted_order_no} 已被删除"))
    _pending_tasks.add(task)
    task.add_done_callback(_log_background_task_exception)
    task.add_done_callback(_pending_tasks.discard)

    logger.info(f'订单删除成功：{deleted_order_no}，操作人：{current_user.username}，抵扣回滚：{total_deducted}')
    return {'success': True, 'message': f'订单删除成功！抵扣回滚数量：{total_deducted}', 'requires_approval': False}

async def _generate_order_number(db: AsyncSession) -> str:
    from fastapi_app.services.numbering import generate_order_number
    return await generate_order_number(db)
