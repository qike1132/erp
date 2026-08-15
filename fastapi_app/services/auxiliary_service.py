"""
辅助业务编排服务

将 auxiliary.py endpoint 中的多 service 编排逻辑下沉到此层，
使 endpoint 只负责参数校验和调用单一 service 函数。

包含：批量订单/入库/出库提交的完整编排（创建 + 缓存失效 + 事件发布）。
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.cache import CacheDomain
from fastapi_app.core.cache_invalidation import InvalidationStrategy, cache_mgr
from fastapi_app.core.domain_events import DomainEvent, DomainEventType, publish as publish_domain_event
from fastapi_app.core.exception_handler import safe_publish_event
from fastapi_app.core.exceptions import db_transaction
from fastapi_app.services.notification_service import StockEvent, publish_stock_event
from fastapi_app.services.order_service import batch_create_orders
from fastapi_app.services.stock_service import (
    batch_create_stockins,
    batch_create_stockouts,
)
from fastapi_app.shared_models import Product

logger = logging.getLogger(__name__)


async def orchestrate_batch_orders(db: AsyncSession, orders_data: list[dict]) -> dict:
    """编排批量订单提交：创建订单 → 缓存失效 → 事件发布"""
    try:
        async with db_transaction(db):
            result = await batch_create_orders(db, orders_data)

        await cache_mgr.invalidate(InvalidationStrategy.DOMAIN, CacheDomain.ORDER_AND_INVENTORY)
        # 失效 dashboard 统计缓存（order_today/order_yesterday 受影响）
        # 与单条 orders/create 端点保持一致（order.py:96）
        await cache_mgr.invalidate_dashboard()

        created_order_ids = result.pop('created_order_ids', [])

        if created_order_ids:
            try:
                await publish_stock_event(StockEvent.ORDER_CREATED, {
                    'order_ids': created_order_ids,
                    'count': len(created_order_ids),
                })
            except (RuntimeError, OSError, ValueError):
                logger.warning("批量订单事件发布失败", exc_info=True)

        return result
    except (SQLAlchemyError, RuntimeError):
        raise


async def orchestrate_batch_stockins(db: AsyncSession, stockins_data: list[dict]) -> dict:
    """编排批量入库提交：创建入库 → 缓存失效"""
    try:
        async with db_transaction(db):
            result = await batch_create_stockins(db, stockins_data)

        await cache_mgr.invalidate(
            InvalidationStrategy.DOMAIN,
            CacheDomain.ORDER_AND_INVENTORY | CacheDomain.STOCKIN,
        )

        return result
    except (SQLAlchemyError, RuntimeError):
        raise


async def orchestrate_batch_stockouts(db: AsyncSession, stockouts_data: list[dict]) -> dict:
    """编排批量出库提交：创建出库 → 缓存失效 → 采购计划重算 → 事件发布"""
    async with db_transaction(db):
        result = await batch_create_stockouts(db, stockouts_data)

    # Post-commit: cache invalidation + 采购计划重算 + 事件发布
    try:
        await cache_mgr.invalidate(InvalidationStrategy.DOMAIN, CacheDomain.ORDER_AND_INVENTORY)
        # 失效 dashboard 统计缓存（stockout_today 受影响）
        await cache_mgr.invalidate_dashboard()

        successful_pairs: set[tuple[int, str]] = set()
        for idx, item in enumerate(stockouts_data):
            r = result['results'][idx]
            if r.get('success'):
                successful_pairs.add((item['product_id'], item['customer']))

        if successful_pairs:
            unique_product_ids = {pid for pid, _ in successful_pairs}
            product_result = await db.execute(
                select(Product.id, Product.name).where(Product.id.in_(unique_product_ids))
            )
            product_name_map = {row[0]: row[1] for row in product_result.all()}
            now_month = datetime.now(timezone.utc).strftime('%Y-%m')
            for product_id, customer in successful_pairs:
                product_name = product_name_map.get(product_id, '')
                if product_name:
                    # 通过领域事件总线发布 STOCK_OUT_CREATED，由 purchase_plan_service 订阅处理
                    # （recalc_plans_after_stockout_create + _invalidate_plan_caches）
                    try:
                        await publish_domain_event(DomainEvent(
                            event_type=DomainEventType.STOCK_OUT_CREATED,
                            domain='stock',
                            payload={
                                'customer': customer,
                                'product_name': product_name,
                                'plan_month': now_month,
                            },
                        ))
                    except Exception:  # defensive: 领域事件发布失败不应影响出库主流程
                        logger.warning("领域事件 STOCK_OUT_CREATED 发布失败", exc_info=True)

            for product_id, _ in successful_pairs:
                product = await db.get(Product, product_id)
                if product is not None:
                    total_qty = sum(
                        item['quantity'] for item in stockouts_data
                        if item['product_id'] == product_id
                    )
                    await safe_publish_event(
                        publish_stock_event, StockEvent.STOCK_CHANGED,
                        {
                            'product_id': product_id,
                            'product_name': product.name,
                            'change_type': '出库',
                            'quantity': total_qty,
                            'current_stock': product.current_stock,
                        },
                        context="批量出库事件发布",
                    )
    except Exception as e:  # defensive: 出库后置操作失败不应影响出库结果
        logger.warning(f"出库后置操作部分失败（不影响出库结果）: {e}", exc_info=True)

    return result
