"""
入库（StockIn）业务逻辑

包含入库核心 CRUD（*_core）与对外编排函数（create/update/delete/batch_create）。

说明：内部对 generate_stockin_number / get_product_for_update / log_inventory_change /
publish_stock_event / 同模块 *_core 的引用统一通过 `stock_service.<name>` 解析，
以便测试通过 `fastapi_app.services.stock_service.<name>` 打 patch 时能够拦截，
同时保持对外命名空间一致。底部 import 该模块以避免循环依赖。
"""
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fastapi_app.core.business_rules import MAX_QUANTITY
from fastapi_app.core.cache_invalidation import cache_mgr, schedule_post_commit_invalidation
from fastapi_app.core.exception_handler import safe_publish_event
from fastapi_app.services.notification_service import StockEvent
from fastapi_app.services.stock_common import _parse_date_preserve_time
from fastapi_app.shared_models import Product, StockIn

logger = logging.getLogger(__name__)

MAX_STOCK_QUANTITY = MAX_QUANTITY  # 库存数量上限，超过此值拒绝操作（值统一由 business_rules 管理）


async def create_stockin_core(db: AsyncSession, product_id: int, quantity: int, customer: str, stockin_date: datetime, note: str, order_type: str = 'regular', country: str | None = None) -> StockIn:
    if quantity <= 0:
        raise ValueError('入库数量必须大于 0')
    if quantity > MAX_STOCK_QUANTITY:
        raise ValueError(f'入库数量不能超过 {MAX_STOCK_QUANTITY}')
    stockin = StockIn(stockin_no=await stock_service.generate_stockin_number(db), product_id=product_id, quantity=quantity, customer=customer, stockin_date=stockin_date, note=note, order_type=order_type, country=country)
    db.add(stockin)
    product = await stock_service.get_product_for_update(db, product_id)
    product.current_stock += quantity
    await db.flush()  # 单次 flush：同时写入 StockIn INSERT + Product UPDATE，并填充 stockin.id
    stock_service.log_inventory_change(db, product_id=product_id, change_type='入库', change_quantity=quantity, related_id=str(stockin.id), note=f'入库ID：{stockin.id}')
    return stockin  # 日志条目由调用方的 flush/commit 写入


async def update_stockin_core(db: AsyncSession, stockin: StockIn, quantity: int, customer: str, stockin_date: datetime, note: str, order_type: str = 'regular', country: str | None = None) -> StockIn:
    result = await db.execute(select(StockIn).where(StockIn.id == stockin.id).with_for_update())
    stockin = result.scalar_one_or_none()
    if not stockin:
        raise ValueError('入库记录不存在')
    old_quantity = stockin.quantity
    stockin.quantity = quantity
    stockin.customer = customer
    stockin.stockin_date = stockin_date
    stockin.note = note
    stockin.order_type = order_type
    stockin.country = country
    if quantity != old_quantity:
        product = await stock_service.get_product_for_update(db, stockin.product_id)
        product.current_stock += quantity - old_quantity
        stock_service.log_inventory_change(db, product_id=stockin.product_id, change_type='入库修改', change_quantity=quantity - old_quantity, related_id=str(stockin.id), note=f'入库修改ID：{stockin.id}')
    await db.flush()
    return stockin


async def delete_stockin_core(db: AsyncSession, stockin: StockIn) -> None:
    if stockin.stockin_stockouts:
        raise ValueError('该入库记录已有出库关联，无法删除')
    product = await stock_service.get_product_for_update(db, stockin.product_id)
    if product.current_stock - stockin.quantity < 0:
        raise ValueError(f'删除入库记录将导致库存为负数（产品：{product.name}，当前库存：{product.current_stock}，入库数量：{stockin.quantity}）')
    product.current_stock -= stockin.quantity
    stock_service.log_inventory_change(db, product_id=stockin.product_id, change_type='入库删除', change_quantity=-stockin.quantity, related_id=str(stockin.id), note=f'入库删除ID：{stockin.id}')
    await db.delete(stockin)
    await db.flush()


async def create_stockin(db: AsyncSession, product_id: int, quantity: int, customer: str, stockin_date_str: str, note: str) -> dict:
    """创建入库记录"""
    stockin_date = _parse_date_preserve_time(stockin_date_str)
    stockin = await stock_service.create_stockin_core(db, product_id, quantity, customer, stockin_date, note)
    await db.flush()
    await cache_mgr.invalidate_stock_and_order()
    schedule_post_commit_invalidation(db, cache_mgr.invalidate_stock_and_order)
    product = await db.get(Product, product_id)
    if product is not None:
        await safe_publish_event(stock_service.publish_stock_event, StockEvent.STOCK_CHANGED, {'product_id': product_id, 'product_name': product.name, 'change_type': '入库', 'quantity': quantity, 'current_stock': product.current_stock}, context="入库事件发布")
    else:
        logger.warning('入库事件发布失败：产品ID %s 不存在', product_id)
    logger.info(f'入库添加成功：{stockin.stockin_no}，客户：{customer}，产品ID：{product_id}，数量：{quantity}')
    return {'id': stockin.id, 'stockin_no': stockin.stockin_no}


async def update_stockin(db: AsyncSession, stockin_id: int, quantity: int, customer: str, stockin_date_str: str, note: str) -> None:
    """更新入库记录"""
    result = await db.execute(select(StockIn).where(StockIn.id == stockin_id).options(selectinload(StockIn.stockin_stockouts)).with_for_update())
    stockin_obj = result.scalar_one_or_none()
    if not stockin_obj:
        raise ValueError('入库记录不存在')
    stockin_date = _parse_date_preserve_time(stockin_date_str, stockin_obj.stockin_date)
    old_quantity = stockin_obj.quantity
    old_stockin_no = stockin_obj.stockin_no
    await update_stockin_core(db, stockin_obj, quantity, customer, stockin_date, note)
    await db.flush()
    await cache_mgr.invalidate_stock_and_order()
    schedule_post_commit_invalidation(db, cache_mgr.invalidate_stock_and_order)
    product = await db.get(Product, stockin_obj.product_id)
    if product is not None:
        await safe_publish_event(stock_service.publish_stock_event, StockEvent.STOCK_CHANGED, {'product_id': stockin_obj.product_id, 'product_name': product.name, 'change_type': '入库编辑', 'quantity': quantity, 'current_stock': product.current_stock}, context="入库编辑事件发布")
    logger.info(f'入库编辑成功：{old_stockin_no}，数量变更：{old_quantity} -> {quantity}')


async def delete_stockin(db: AsyncSession, stockin_id: int) -> None:
    """删除入库记录"""
    result = await db.execute(select(StockIn).where(StockIn.id == stockin_id).options(selectinload(StockIn.stockin_stockouts)).with_for_update())
    stockin_obj = result.scalar_one_or_none()
    if not stockin_obj:
        raise ValueError('入库记录不存在')
    stockin_no = stockin_obj.stockin_no
    await stock_service.delete_stockin_core(db, stockin_obj)
    await db.flush()
    await cache_mgr.invalidate_stock_and_order()
    schedule_post_commit_invalidation(db, cache_mgr.invalidate_stock_and_order)
    product = await db.get(Product, stockin_obj.product_id)
    if product is not None:
        await safe_publish_event(stock_service.publish_stock_event, StockEvent.STOCK_CHANGED, {'product_id': stockin_obj.product_id, 'product_name': product.name, 'change_type': '入库删除', 'quantity': -stockin_obj.quantity, 'current_stock': product.current_stock}, context="入库删除事件发布")
    logger.info(f'入库删除成功：{stockin_no}，数量：{stockin_obj.quantity}')


async def batch_create_stockins(db: AsyncSession, stockins_data: list) -> dict:
    """批量创建入库记录"""
    validated = []
    errors_map = {}
    for idx, item in enumerate(stockins_data):
        product_id = item.get('product_id')
        customer = str(item.get('customer', '')).strip()
        quantity = item.get('quantity', 0)
        if not all([product_id, customer, quantity]):
            errors_map[idx] = '缺少必填字段或数量无效'
            continue
        if int(quantity) <= 0:
            errors_map[idx] = '入库数量必须大于0'
            continue
        validated.append((idx, item))
    results = [None] * len(stockins_data)
    for idx, err in errors_map.items():
        results[idx] = {'success': False, 'error': err, 'id': stockins_data[idx].get('id', '未知')}
    if validated:
        for orig_idx, item in validated:
            product_id = item.get('product_id')
            customer = str(item.get('customer', '')).strip()
            quantity = int(item.get('quantity', 0))
            note = item.get('note', '')
            order_type = item.get('order_type', 'regular') or 'regular'
            country = item.get('country') or None
            stockin_date_str = item.get('stockin_date') or ''
            stockin_date = _parse_date_preserve_time(stockin_date_str) if stockin_date_str else datetime.now(UTC).replace(tzinfo=None)  # naive UTC: DB列类型为 TIMESTAMP WITHOUT TIME ZONE
            try:
                async with db.begin_nested():
                    stockin = await stock_service.create_stockin_core(db, product_id, quantity, customer, stockin_date, note, order_type, country)
                results[orig_idx] = {'success': True, 'stockin_no': stockin.stockin_no, 'id': stockin.id}
            except ValueError as e:
                results[orig_idx] = {'success': False, 'error': str(e), 'id': item.get('id', '未知')}
            except (TypeError, OSError) as e:
                logger.error(f'批量入库单项失败: {e}', exc_info=True)
                results[orig_idx] = {'success': False, 'error': str(e) or '入库处理失败，请稍后重试', 'id': item.get('id', '未知')}
        await db.flush()
    return {'success': True, 'results': results}


# 底部引入 stock_service 以提供命名空间解析（延迟到调用期，避免循环依赖）
from fastapi_app.services import stock_service
