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
from fastapi_app.services.stock_common import guard_stockout_deletion
from fastapi_app.shared.stock_concurrency import (
    get_product_for_update,
    update_stock_with_optimistic_lock,
)
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


async def _invalidate_order_domains() -> None:
    """失效订单/库存与报表域缓存（提交前后共用；与 commands.py 同口径）。"""
    await cache_mgr.invalidate(
        InvalidationStrategy.DOMAIN,
        CacheDomain.ORDER_AND_INVENTORY | CacheDomain.REPORT,
    )



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

    # 取锁顺序必须与批量创建路径一致（**Product → StockIn**），否则并发时死锁：
    # order_batch_create 先 _lock_products 按全局升序锁 Product、再在
    # process_order_deduction 锁 StockIn；本函数原先反过来（先 StockIn 后 Product），
    # 两条路径命中同一产品/同一批备货时会互相等锁 → PostgreSQL 检出后回滚其一
    # （表现为 500/409，无数据损坏）。先锁 Product 与对方对齐即消除这个环。
    # P2-A2 类型收窄：order.product_id 列可空；None 时抛出的文案与 get_product_for_update 内部逐字一致
    order_product_id = order.product_id
    if order_product_id is None:
        raise ValueError(f'产品ID {order_product_id} 不存在')
    product = await get_product_for_update(db, order_product_id)

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
        # P2-A2 类型收窄：IN 过滤已保证 stockin_id 非 NULL，显式过滤 None 只影响类型（结果集不变）
        deducted_map = {row[0]: row[1] for row in deducted_rows.all() if row[0] is not None}

    # 预检可用备货总量（P1-8）：不足时在写任何 StockOut/库存之前失败，
    # 失败路径不产生半成品记录（回滚边界由调用方 db_transaction 提供）
    available_total = sum(
        max(0, stockin.quantity - int(deducted_map.get(stockin.id, 0)))
        for stockin in stockins
    )
    if available_total < diff:
        raise ValueError(f'可用备货不足，还需{diff - available_total}件无法抵扣')

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
            stockout_date=datetime.now(UTC),  # aware UTC：stockout_date 列为 timestamptz
            product_id=stockin.product_id,
            quantity=deduct_amount,
            customer=order.customer,
            order_id=order.id,
            stockin_id=stockin.id,
            note=f'[订单抵扣]{order.order_no}'
        )
        db.add(stockout)

        # 更新产品库存（统一走乐观锁写入口，WHERE version=旧值；不再直写 current_stock）
        if product and deduct_amount > 0:
            await update_stock_with_optimistic_lock(db, order_product_id, -deduct_amount)

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
    # P2-A2 类型收窄：order.product_id 列可空；None 时抛出的文案与 get_product_for_update 内部逐字一致
    order_product_id = order.product_id
    if order_product_id is None:
        raise ValueError(f'产品ID {order_product_id} 不存在')
    product = await get_product_for_update(db, order_product_id)

    # 预检现有抵扣总量（P1-8）：请求减少量超过现有抵扣量时在写任何记录之前失败
    effective_total = sum(
        max(0, stockout.quantity - stockout.returned_quantity)
        for stockout in deduction_stockouts
    )
    if effective_total < reduce_amount:
        raise ValueError(
            f'现有抵扣量不足，还需{reduce_amount - effective_total}件无法减少'
        )

    remaining = reduce_amount
    logs: list[InventoryLog] = []
    for stockout in deduction_stockouts:
        if remaining <= 0:
            break
        effective_qty = stockout.quantity - stockout.returned_quantity
        if effective_qty <= 0:
            continue

        if remaining >= effective_qty:
            # 整条删除：先过退货守卫（迁移 072 RESTRICT 的应用层前置）——active 退货
            # 拒绝、已取消退货解除关联。放在库存/日志写入之前，失败时不产生半截副作用。
            await guard_stockout_deletion(db, stockout)
            remaining -= effective_qty
            if product:
                await update_stock_with_optimistic_lock(db, order_product_id, effective_qty)
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
                await update_stock_with_optimistic_lock(db, order_product_id, remaining)
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

    if remaining > 0:
        raise ValueError(f'现有抵扣量不足，还需{remaining}件无法减少')


async def update_deduct_quantity(
    db: AsyncSession, order_id: int, new_deduct_quantity: int, current_user: User,
) -> dict:
    """更新订单的抵扣备货数量。

    逻辑：
    - 查询当前抵扣量（StockOut where order_id=X and stockin_id IS NOT NULL）
    - 如果 new > current：增加抵扣（从可用备货中扣除）
    - 如果 new < current：减少抵扣（删除/减少已有的抵扣出库记录）
    - 如果 new == current：无变化

    完整性（P1-8）：抵扣不足时抛 ValueError（文案含还差多少件），不做静默截断；
    返回的 deduct_quantity 以 flush 后从 DB 重新聚合的实际生效量为准，任何
    「未完全生效」路径都不返回 success=True。函数内不 commit/rollback ——
    失败回滚由调用方（端点 db_transaction）边界保证。
    """
    # 第十四轮：锁序统一为 Product→Order —— 出库创建路径是先锁 Product
    # （create_stockout_core）再经 calculate_available_shipment_quantity 锁同客户全部
    # Order；本函数原为 Order→Product（锁订单后 _increase/_decrease_deduction 再锁
    # 产品），同产品+同客户「创建出库 vs 修改抵扣」并发会互等行锁死锁。
    # 先无锁读 product_id 预锁产品；读不到（订单不存在/product_id 空）则跳过预锁，
    # 由下方加锁后的既有校验按原口径抛「订单不存在」，语义不变。
    _pid = (await db.execute(
        select(Order.product_id).where(Order.id == order_id)
    )).scalar_one_or_none()
    if _pid is not None:
        await get_product_for_update(db, _pid)

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

    # 先把本次抵扣变更 flush（不 commit）到会话，再核对实际生效量（P1-8）
    await db.flush()

    actual_map = await _batch_deduct_quantities(db, [order_id])
    actual_deduct = actual_map.get(order_id, 0)
    if actual_deduct != new_deduct_quantity:
        raise ValueError(
            f'抵扣数量未能完全生效：请求{new_deduct_quantity}件，实际生效{actual_deduct}件'
        )

    # 更新订单状态（抵扣量已落地，状态派生与实际一致）
    order.status = await compute_order_status_from_db(db, order)

    # 对齐 commands.py 标准模式（Z01-R2）：提交前失效广覆盖 + 提交后二次失效兜底，
    # 且缓存基础设施异常只降级告警，不得打断抵扣修改事务。
    try:
        await _invalidate_order_domains()
    except INFRA_EXCEPTIONS as e:
        logger.warning('缓存清除失败: %s', e)
    schedule_post_commit_invalidation(db, _invalidate_order_domains)
    await _safe_invalidate_purchase_cache()

    logger.info(f'订单抵扣修改：{order.order_no}，{current_deduct}->{actual_deduct}，操作人：{current_user.username}')

    return {'success': True, 'message': '抵扣数量修改成功', 'deduct_quantity': actual_deduct}
