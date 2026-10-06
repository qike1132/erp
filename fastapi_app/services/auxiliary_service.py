"""
辅助业务编排服务

将 auxiliary.py endpoint 中的多 service 编排逻辑下沉到此层，
使 endpoint 只负责参数校验和调用单一 service 函数。

包含：批量订单/入库/出库提交的完整编排（创建 + 缓存失效 + 事件发布）。
"""
import logging
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from fastapi_app.core.cache import CacheDomain
from fastapi_app.core.cache_invalidation import InvalidationStrategy, cache_mgr
from fastapi_app.core.domain_events import DomainEvent, DomainEventType
from fastapi_app.core.domain_events import publish as publish_domain_event
from fastapi_app.core.exception_handler import safe_publish_event
from fastapi_app.core.exceptions import BusinessError, NotFoundError, db_transaction
from fastapi_app.services.notification_service import StockEvent, publish_stock_event
from fastapi_app.shared_models import (
    InventoryLog,
    Product,
    ProductAccessory,
    ProductFabric,
    ProductMaterial,
    PurchaseOrder,
    StockIn,
    Supplier,
)

logger = logging.getLogger(__name__)


async def orchestrate_batch_orders(db: AsyncSession, orders_data: list[dict], created_by: str = '') -> dict:
    """编排批量订单提交：创建订单 → 出货计划同步（同事务）→ 缓存失效 → 事件发布"""
    from fastapi_app.services.order_service import batch_create_orders
    try:
        async with db_transaction(db):
            result = await batch_create_orders(db, orders_data, created_by=created_by)

        await cache_mgr.invalidate(
            InvalidationStrategy.DOMAIN,
            CacheDomain.ORDER_AND_INVENTORY | CacheDomain.REPORT,
        )
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


async def orchestrate_batch_stockins(db: AsyncSession, stockins_data: list[dict], operator_id: int | None = None) -> dict:
    """编排批量入库提交：创建入库 → 缓存失效"""
    from fastapi_app.services.stock_service import batch_create_stockins
    try:
        async with db_transaction(db):
            result = await batch_create_stockins(db, stockins_data, operator_id=operator_id)

        await cache_mgr.invalidate(
            InvalidationStrategy.DOMAIN,
            CacheDomain.ORDER_AND_INVENTORY | CacheDomain.STOCKIN | CacheDomain.REPORT,
        )

        return result
    except (SQLAlchemyError, RuntimeError):
        raise


async def orchestrate_batch_stockouts(db: AsyncSession, stockouts_data: list[dict], operator_id: int | None = None) -> dict:
    """编排批量出库提交：创建出库 → 缓存失效 → 采购计划重算 → 事件发布"""
    from fastapi_app.services.stock_service import batch_create_stockouts
    async with db_transaction(db):
        result = await batch_create_stockouts(db, stockouts_data, operator_id=operator_id)

    # Post-commit: cache invalidation + 采购计划重算 + 事件发布
    try:
        await cache_mgr.invalidate(
            InvalidationStrategy.DOMAIN,
            CacheDomain.ORDER_AND_INVENTORY | CacheDomain.REPORT,
        )
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
                select(Product).where(Product.id.in_(unique_product_ids))
            )
            product_map = {p.id: p for p in product_result.scalars().all()}
            now_month = datetime.now(UTC).strftime('%Y-%m')
            for product_id, customer in successful_pairs:
                product = product_map.get(product_id)
                product_name = product.name if product is not None else ''
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
                product = product_map.get(product_id)
                if product is not None:
                    # 第八轮审计：原 sum 遍历全部 stockouts_data（含 success=False 的失败行）
                    # → 同产品部分失败时上报的变动数量偏大。改为只累计成功行。
                    total_qty = sum(
                        item['quantity'] for idx, item in enumerate(stockouts_data)
                        if item['product_id'] == product_id
                        and result['results'][idx].get('success')
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


# ==================== 查询函数（自 auxiliary.py 端点下沉，纯查询搬移） ====================
# 产品搜索已统一委托 ProductSearchService 模块级单例（2026-08-22 批次 2-4；S8 起不再经 core.container）


async def get_product_by_id(db: AsyncSession, product_id: int) -> Product | None:
    """按 ID 获取产品"""
    return await db.get(Product, product_id)


async def count_inventory_logs(db: AsyncSession, product_id: int) -> int:
    """统计产品库存日志总数"""
    count_result = await db.execute(
        select(func.count(InventoryLog.id)).where(InventoryLog.product_id == product_id)
    )
    return count_result.scalar() or 0


async def get_inventory_logs_page(db: AsyncSession, product_id: int, page: int, per_page: int) -> list[InventoryLog]:
    """分页获取产品库存日志（按变更时间倒序）"""
    result = await db.execute(
        select(InventoryLog).where(InventoryLog.product_id == product_id)
        .order_by(InventoryLog.change_date.desc())
        .offset((page - 1) * per_page).limit(per_page)
    )
    return list(result.scalars().all())


async def get_available_stockins(
    db: AsyncSession, product_id: int | None, customer: str, limit: int,
) -> list[StockIn]:
    """获取可用入库记录（含出库关联与产品信息，按入库时间升序，限制返回数量）"""
    query = select(StockIn).options(
        joinedload(StockIn.stockin_stockouts), joinedload(StockIn.product)
    )

    if product_id:
        query = query.where(StockIn.product_id == product_id)
    if customer:
        query = query.where(StockIn.customer == customer)

    query = query.order_by(StockIn.stockin_date.asc()).limit(limit)
    result = await db.execute(query)
    return list(result.unique().scalars().all())


async def get_stockin_by_id(db: AsyncSession, stockin_id: int) -> StockIn | None:
    """按 ID 获取入库记录"""
    return await db.get(StockIn, stockin_id)


async def get_supplier_by_id(db: AsyncSession, supplier_id: int) -> Supplier | None:
    """按 ID 获取供应商"""
    result = await db.execute(select(Supplier).where(Supplier.id == supplier_id))
    return result.scalar_one_or_none()


async def supplier_has_bom_or_orders(db: AsyncSession, supplier_id: int) -> bool:
    """检查供应商是否已关联 BOM（物料/面料/辅料）或采购订单数据"""
    has_bom = (
        (await db.execute(select(ProductMaterial.id).where(ProductMaterial.supplier_id == supplier_id).limit(1))).scalar() or
        (await db.execute(select(ProductFabric.id).where(ProductFabric.supplier_id == supplier_id).limit(1))).scalar() or
        (await db.execute(select(ProductAccessory.id).where(ProductAccessory.supplier_id == supplier_id).limit(1))).scalar()
    )
    has_orders = (await db.execute(select(PurchaseOrder.id).where(PurchaseOrder.supplier_id == supplier_id).limit(1))).scalar()
    return bool(has_bom or has_orders)


# ==================== 写操作（自 auxiliary.py 端点下沉） ====================
async def delete_supplier(db: AsyncSession, supplier_id: int) -> None:
    """删除供应商（含 BOM/采购订单关联检查）。

    Args:
        db: 异步数据库会话。
        supplier_id: 供应商 ID。

    Raises:
        NotFoundError: 404 供应商不存在。
        BusinessError: 400 存在关联数据，无法删除。
    """
    supplier = await get_supplier_by_id(db, supplier_id)
    if not supplier:
        raise NotFoundError("供应商不存在")

    if await supplier_has_bom_or_orders(db, supplier_id):
        raise BusinessError("该供应商已有相关BOM或采购订单数据，无法删除")

    await db.delete(supplier)
    await db.flush()  # flush-only：提交由请求级 get_async_db 统一负责


async def get_system_stats() -> dict:
    """获取系统统计信息（缓存命中率/性能数据）。

    Returns:
        dict: 包含 cache 和 performance 统计的字典。
    """
    try:
        from utils.performance_monitor import performance_monitor, query_tracker

        return {
            'cache': {},
            'performance': {
                **performance_monitor.get_stats(),
                'queries': query_tracker.get_stats()
            }
        }
    except (ImportError, AttributeError) as e:
        # 不静默吞掉：模块本身出问题时必须留痕，否则又是「接口 500 无人知」
        logger.warning('系统统计不可用: %s', e, exc_info=True)
        return {'cache': {}, 'performance': {}}
