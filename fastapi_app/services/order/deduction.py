"""订单抵扣（FIFO 增/减抵扣与抵扣量修改）

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



from fastapi_app.services.order.approval_flow import _check_order_lock


async def _increase_deduction(
    db: AsyncSession, order: Order, diff: int,
) -> None:
    """增加抵扣：从可用备货中按 FIFO 扣除。

    Args:
        db: 异步会话
        order: 目标订单（已加行锁）
        diff: 需增加的抵扣量（正数）

    Raises:
        ValueError: 可用备货不足
    """
    from fastapi_app.services.numbering import generate_stockout_number

    stockins_result = await db.execute(
        select(StockIn)
        .where(StockIn.product_id == order.product_id, StockIn.customer == order.customer)
        .order_by(StockIn.stockin_date.asc(), StockIn.id.asc())
        .with_for_update()
    )
    stockins = stockins_result.scalars().all()

    # 批量查询所有备货的已抵扣量（消除 N+1 查询）
    stockin_ids = [s.id for s in stockins]
    deducted_map: dict[int, int] = {}
    if stockin_ids:
        deducted_rows = await db.execute(
            select(StockOut.stockin_id, func.coalesce(func.sum(StockOut.quantity - StockOut.returned_quantity), 0))
            .where(StockOut.stockin_id.in_(stockin_ids))
            .group_by(StockOut.stockin_id)
        )
        deducted_map = dict(deducted_rows.all())

    # 循环外一次性锁定产品（消除重复行锁）
    product = await get_product_for_update(db, order.product_id)

    remaining = diff
    logs: list[InventoryLog] = []
    for stockin in stockins:
        if remaining <= 0:
            break
        already_deducted = int(deducted_map.get(stockin.id, 0))
        available = stockin.quantity - already_deducted
        if available <= 0:
            continue

        deduct_amount = min(remaining, available)
        stockout_no = await generate_stockout_number(db)
        stockout = StockOut(
            stockout_no=stockout_no,
            stockout_date=datetime.now(UTC).replace(tzinfo=None),
            product_id=stockin.product_id,
            quantity=deduct_amount,
            customer=order.customer,
            order_id=order.id,
            stockin_id=stockin.id,
            note=f'[订单抵扣]{order.order_no}'
        )
        db.add(stockout)

        # 更新产品库存（循环外已锁定，循环内直接修改）
        if product and deduct_amount > 0:
            product.current_stock -= deduct_amount

        logs.append(InventoryLog(
            product_id=order.product_id,
            change_type='订单抵扣',
            change_quantity=-deduct_amount,
            related_id=stockout_no,
            note=f'修改抵扣增加：订单{order.order_no}，备货{stockin.stockin_no}，数量{deduct_amount}'
        ))
        remaining -= deduct_amount

    if logs:
        db.add_all(logs)

    if remaining > 0:
        raise ValueError(f'可用备货不足，还需{remaining}件无法抵扣')

async def _decrease_deduction(
    db: AsyncSession, order: Order, order_id: int, reduce_amount: int,
) -> None:
    """减少抵扣：按时间倒序删除/减少已有的抵扣出库记录。

    Args:
        db: 异步会话
        order: 目标订单（已加行锁）
        order_id: 订单 ID
        reduce_amount: 需减少的抵扣量（正数）
    """
    stockouts_result = await db.execute(
        select(StockOut)
        .where(StockOut.order_id == order_id, StockOut.stockin_id.isnot(None))
        .order_by(StockOut.id.desc())
        .with_for_update()
    )
    deduction_stockouts = stockouts_result.scalars().all()

    # 循环外一次性锁定产品（消除重复行锁）
    product = await get_product_for_update(db, order.product_id)

    remaining = reduce_amount
    logs: list[InventoryLog] = []
    for stockout in deduction_stockouts:
        if remaining <= 0:
            break
        effective_qty = stockout.quantity - stockout.returned_quantity
        if effective_qty <= 0:
            continue

        if remaining >= effective_qty:
            # 整条删除
            remaining -= effective_qty
            if product:
                product.current_stock += effective_qty
            logs.append(InventoryLog(
                product_id=order.product_id,
                change_type='取消抵扣',
                change_quantity=effective_qty,
                related_id=stockout.stockout_no,
                note=f'修改抵扣减少：订单{order.order_no}，取消出库{stockout.stockout_no}，数量{effective_qty}'
            ))
            await db.delete(stockout)
        else:
            # 部分减少
            stockout.quantity -= remaining
            if product:
                product.current_stock += remaining
            logs.append(InventoryLog(
                product_id=order.product_id,
                change_type='取消抵扣',
                change_quantity=remaining,
                related_id=stockout.stockout_no,
                note=f'修改抵扣减少：订单{order.order_no}，减少出库{stockout.stockout_no}，数量{remaining}'
            ))
            remaining = 0

    if logs:
        db.add_all(logs)

async def update_deduct_quantity(
    db: AsyncSession, order_id: int, new_deduct_quantity: int, current_user: User,
) -> dict:
    """更新订单的抵扣备货数量。

    逻辑：
    - 查询当前抵扣量（StockOut where order_id=X and stockin_id IS NOT NULL）
    - 如果 new > current：增加抵扣（从可用备货中扣除）
    - 如果 new < current：减少抵扣（删除/减少已有的抵扣出库记录）
    - 如果 new == current：无变化
    """
    result = await db.execute(select(Order).where(Order.id == order_id).with_for_update())
    order = result.scalar_one_or_none()
    if not order or order.is_deleted:
        raise ValueError('订单不存在')

    await _check_order_lock(db, order_id, order, current_user, '修改抵扣')

    if new_deduct_quantity < 0:
        raise ValueError('抵扣数量不能为负数')

    # 查询当前抵扣量
    deduct_map = await _batch_deduct_quantities(db, [order_id])
    current_deduct = deduct_map.get(order_id, 0)

    if new_deduct_quantity == current_deduct:
        return {'success': True, 'message': '抵扣数量未变化', 'deduct_quantity': current_deduct}

    diff = new_deduct_quantity - current_deduct

    if diff > 0:
        await _increase_deduction(db, order, diff)
    else:  # diff < 0，减少抵扣
        await _decrease_deduction(db, order, order_id, abs(diff))

    # 更新订单状态
    order.status = await compute_order_status_from_db(db, order)

    await db.flush()
    await cache_mgr.invalidate(InvalidationStrategy.DOMAIN, CacheDomain.ORDER_AND_INVENTORY)
    await _safe_invalidate_purchase_cache()

    logger.info(f'订单抵扣修改：{order.order_no}，{current_deduct}->{new_deduct_quantity}，操作人：{current_user.username}')

    return {'success': True, 'message': '抵扣数量修改成功', 'deduct_quantity': new_deduct_quantity}
