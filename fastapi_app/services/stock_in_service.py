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
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fastapi_app.core.business_rules import MAX_QUANTITY
from fastapi_app.core.cache_invalidation import cache_mgr, schedule_post_commit_invalidation
from fastapi_app.core.exception_handler import safe_publish_event
from fastapi_app.services.notification_service import StockEvent
from fastapi_app.services.stock_common import _parse_date_preserve_time
from fastapi_app.shared.stock_concurrency import apply_stock_delta_locked, assert_stock_available
from fastapi_app.shared_models import Product, StockIn
from fastapi_app.utils import inventory_balance_bounds

logger = logging.getLogger(__name__)

MAX_STOCK_QUANTITY = MAX_QUANTITY  # 库存数量上限，超过此值拒绝操作（值统一由 business_rules 管理）


async def create_stockin_core(db: AsyncSession, product_id: int, quantity: int, customer: str, stockin_date: datetime, note: str, operator_id: int | None = None) -> StockIn:
    if quantity <= 0:
        raise ValueError('入库数量必须大于 0')
    if quantity > MAX_STOCK_QUANTITY:
        raise ValueError(f'入库数量不能超过 {MAX_STOCK_QUANTITY}')
    stockin = StockIn(stockin_no=await stock_service.generate_stockin_number(db), product_id=product_id, quantity=quantity, customer=customer, stockin_date=stockin_date, note=note)
    db.add(stockin)
    product = await stock_service.get_product_for_update(db, product_id)
    # 统一写入口：持锁路径也要带 version 守卫并递增 version。
    # 直接 `product.current_stock += quantity` 不会 bump version（Product 无 version_id_col），
    # 与走乐观锁的写入口并发时会因 WHERE version=旧值 仍命中而丢失更新。
    updated = await apply_stock_delta_locked(db, product, quantity)
    await db.flush()  # 单次 flush：同时写入 StockIn INSERT + Product UPDATE，并填充 stockin.id
    # 结存由锁内写入口返回值反推（禁止另行 SELECT：并发下会写出自相矛盾的流水）
    before, after = inventory_balance_bounds(updated.current_stock, quantity)
    stock_service.log_inventory_change(db, product_id=product_id, change_type='入库', change_quantity=quantity, related_id=str(stockin.id), note=f'入库ID：{stockin.id}', quantity_before=before, quantity_after=after, product_name=updated.name, operator_id=operator_id)
    return stockin  # 日志条目由调用方的 flush/commit 写入


async def update_stockin_core(db: AsyncSession, stockin: StockIn, quantity: int, customer: str, stockin_date: datetime, note: str, operator_id: int | None = None) -> StockIn:
    result = await db.execute(select(StockIn).where(StockIn.id == stockin.id).with_for_update())
    stockin_row = result.scalar_one_or_none()
    if not stockin_row:
        raise ValueError('入库记录不存在')
    stockin = stockin_row
    old_quantity = stockin.quantity
    stockin.quantity = quantity
    stockin.customer = customer
    stockin.stockin_date = stockin_date
    stockin.note = note
    if quantity != old_quantity:
        product = await stock_service.get_product_for_update(db, stockin.product_id)
        updated = await apply_stock_delta_locked(db, product, quantity - old_quantity)
        before, after = inventory_balance_bounds(updated.current_stock, quantity - old_quantity)
        stock_service.log_inventory_change(db, product_id=stockin.product_id, change_type='入库修改', change_quantity=quantity - old_quantity, related_id=str(stockin.id), note=f'入库修改ID：{stockin.id}', quantity_before=before, quantity_after=after, product_name=updated.name, operator_id=operator_id)
    await db.flush()
    return stockin


async def delete_stockin_core(db: AsyncSession, stockin: StockIn, operator_id: int | None = None) -> None:
    if stockin.stockin_stockouts:
        raise ValueError('该入库记录已有出库关联，无法删除')
    product = await stock_service.get_product_for_update(db, stockin.product_id)
    # 负库存判定统一走统一入口（P1-2b），文案与改动前逐字一致
    assert_stock_available(
        product.current_stock, -stockin.quantity,
        message=f'删除入库记录将导致库存为负数（产品：{product.name}，当前库存：{product.current_stock}，入库数量：{stockin.quantity}）',
    )
    # 上面的 assert 保留是为了那条逐字固定的自定义文案（有测试锁着）；
    # 写入口统一走 apply_stock_delta_locked 以带上 version 守卫并递增 version。
    updated = await apply_stock_delta_locked(db, product, -stockin.quantity)
    before, after = inventory_balance_bounds(updated.current_stock, -stockin.quantity)
    stock_service.log_inventory_change(db, product_id=stockin.product_id, change_type='入库删除', change_quantity=-stockin.quantity, related_id=str(stockin.id), note=f'入库删除ID：{stockin.id}', quantity_before=before, quantity_after=after, product_name=updated.name, operator_id=operator_id)
    await db.delete(stockin)
    await db.flush()


async def create_stockin(db: AsyncSession, product_id: int, quantity: int, customer: str, stockin_date_str: str, note: str, operator_id: int | None = None) -> dict:
    """创建入库记录"""
    stockin_date = _parse_date_preserve_time(stockin_date_str)
    stockin = await stock_service.create_stockin_core(db, product_id, quantity, customer, stockin_date, note, operator_id=operator_id)
    await db.flush()
    await cache_mgr.invalidate_stock_and_order()
    schedule_post_commit_invalidation(db, cache_mgr.invalidate_stock_and_order)
    product = await db.get(Product, product_id)
    if product is not None:
        await safe_publish_event(stock_service.publish_stock_event, StockEvent.STOCK_CHANGED, {'product_id': product_id, 'product_name': product.name, 'change_type': '入库', 'quantity': quantity, 'current_stock': product.current_stock}, context="入库事件发布")
    else:
        logger.warning('入库事件发布失败：产品ID %s 不存在', product_id)
    logger.info(f'入库添加成功：{stockin.stockin_no}，客户：{customer}，产品ID：{product_id}，数量：{quantity}')
    # 采购订单自动生成：提交后投递扫描任务（替代采购中心人工「一键审核」）
    from fastapi_app.services.purchase._auto_generate import schedule_auto_generate_purchase_orders
    schedule_auto_generate_purchase_orders(db)
    return {'id': stockin.id, 'stockin_no': stockin.stockin_no}


async def update_stockin(db: AsyncSession, stockin_id: int, quantity: int, customer: str, stockin_date_str: str, note: str, operator_id: int | None = None) -> None:
    """更新入库记录。

    ⚠️ **锁序必须是 Product → StockIn**：order/deduction 与 order_batch_create 都是先锁
    Product 再锁 StockIn。本函数原先反过来（先锁 StockIn，改数量时才锁 Product），
    两条路径命中同一产品/同一条备货时互相等锁 → PG 检出后回滚其一（500/409，无数据损坏）。
    为按序加锁，先用**无锁读**拿到 product_id（该列 NOT NULL 且不可改）。
    """
    product_id = (await db.execute(
        select(StockIn.product_id).where(StockIn.id == stockin_id)
    )).scalar_one_or_none()
    if product_id is None:
        raise ValueError('入库记录不存在')
    product = await stock_service.get_product_for_update(db, product_id)

    result = await db.execute(select(StockIn).where(StockIn.id == stockin_id).options(selectinload(StockIn.stockin_stockouts)).with_for_update())
    stockin_obj = result.scalar_one_or_none()
    if not stockin_obj:
        raise ValueError('入库记录不存在')
    stockin_date = _parse_date_preserve_time(stockin_date_str, stockin_obj.stockin_date)
    old_quantity = stockin_obj.quantity
    if quantity != old_quantity:
        # 与 delete_stockin_core 的两道保护对称：有出库关联的入库不允许改数量
        # （出库记录引用的入库数量会失真），减量也不得把当前库存打成负数。
        if stockin_obj.stockin_stockouts:
            raise ValueError('该入库记录已有出库关联，不能修改数量；可修改客户/日期/备注')
        # 负库存判定统一走统一入口（P1-2b），文案与改动前逐字一致
        assert_stock_available(
            product.current_stock, quantity - old_quantity,
            message=f'修改入库数量将导致库存为负数（产品：{product.name}，当前库存：{product.current_stock}，变更量：{quantity - old_quantity}）',
        )
    old_stockin_no = stockin_obj.stockin_no
    await update_stockin_core(db, stockin_obj, quantity, customer, stockin_date, note, operator_id=operator_id)
    await db.flush()
    await cache_mgr.invalidate_stock_and_order()
    schedule_post_commit_invalidation(db, cache_mgr.invalidate_stock_and_order)
    notify_product = await db.get(Product, stockin_obj.product_id)
    if notify_product is not None:
        await safe_publish_event(stock_service.publish_stock_event, StockEvent.STOCK_CHANGED, {'product_id': stockin_obj.product_id, 'product_name': notify_product.name, 'change_type': '入库编辑', 'quantity': quantity, 'current_stock': notify_product.current_stock}, context="入库编辑事件发布")
    logger.info(f'入库编辑成功：{old_stockin_no}，数量变更：{old_quantity} -> {quantity}')


async def delete_stockin(db: AsyncSession, stockin_id: int, operator_id: int | None = None) -> None:
    """删除入库记录。

    ⚠️ 锁序同 update_stockin：**Product → StockIn**（`delete_stockin_core` 内部会锁
    Product，若这里先锁 StockIn 就构成反序）。故先用无锁读拿 product_id 再按序加锁。
    """
    product_id = (await db.execute(
        select(StockIn.product_id).where(StockIn.id == stockin_id)
    )).scalar_one_or_none()
    if product_id is None:
        raise ValueError('入库记录不存在')
    await stock_service.get_product_for_update(db, product_id)

    result = await db.execute(select(StockIn).where(StockIn.id == stockin_id).options(selectinload(StockIn.stockin_stockouts)).with_for_update())
    stockin_obj = result.scalar_one_or_none()
    if not stockin_obj:
        raise ValueError('入库记录不存在')
    stockin_no = stockin_obj.stockin_no
    await stock_service.delete_stockin_core(db, stockin_obj, operator_id=operator_id)
    await db.flush()
    await cache_mgr.invalidate_stock_and_order()
    schedule_post_commit_invalidation(db, cache_mgr.invalidate_stock_and_order)
    product = await db.get(Product, stockin_obj.product_id)
    if product is not None:
        await safe_publish_event(stock_service.publish_stock_event, StockEvent.STOCK_CHANGED, {'product_id': stockin_obj.product_id, 'product_name': product.name, 'change_type': '入库删除', 'quantity': -stockin_obj.quantity, 'current_stock': product.current_stock}, context="入库删除事件发布")
    logger.info(f'入库删除成功：{stockin_no}，数量：{stockin_obj.quantity}')
    # 备货记录没了 → 撤销引用它的 pending 采购单（与客户订单删除走 ORDER_DELETED 清理同款；
    # 备货删除此前漏了这条，会留下拿着已不存在来源的采购单）。
    from fastapi_app.services.purchase_order_revoke import schedule_stockin_deleted_side_effects
    schedule_stockin_deleted_side_effects(db, stockin_id)


async def batch_create_stockins(db: AsyncSession, stockins_data: list, operator_id: int | None = None) -> dict:
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
    results: list[dict[str, Any] | None] = [None] * len(stockins_data)
    for idx, err in errors_map.items():
        results[idx] = {'success': False, 'error': err, 'id': stockins_data[idx].get('id', '未知')}
    if validated:
        for orig_idx, item in validated:
            product_id = item.get('product_id')
            customer = str(item.get('customer', '')).strip()
            quantity = int(item.get('quantity', 0))
            note = item.get('note', '')
            stockin_date_str = item.get('stockin_date') or ''
            # 日期路径返回 aware 北京时间（Z03-R2）；无日期取 aware UTC。列类型 timestamptz，
            # 两者都是 aware，不再依赖机器本地时区解释。
            stockin_date = _parse_date_preserve_time(stockin_date_str) if stockin_date_str else datetime.now(UTC)
            try:
                async with db.begin_nested():
                    stockin = await stock_service.create_stockin_core(db, product_id, quantity, customer, stockin_date, note, operator_id=operator_id)
                results[orig_idx] = {'success': True, 'stockin_no': stockin.stockin_no, 'id': stockin.id}
            except ValueError as e:
                results[orig_idx] = {'success': False, 'error': str(e), 'id': item.get('id', '未知')}
            except (TypeError, OSError) as e:
                logger.error(f'批量入库单项失败: {e}', exc_info=True)
                results[orig_idx] = {'success': False, 'error': str(e) or '入库处理失败，请稍后重试', 'id': item.get('id', '未知')}
        await db.flush()

    if any(isinstance(r, dict) and r.get('success') for r in results):
        # 采购订单自动生成：提交后投递扫描任务（替代采购中心人工「一键审核」）
        from fastapi_app.services.purchase._auto_generate import schedule_auto_generate_purchase_orders
        schedule_auto_generate_purchase_orders(db)
    # Z03-R3：顶层 success 与批量出库的 all_success 对齐，部分失败不再误报成功
    all_success = all(isinstance(r, dict) and r.get('success') for r in results)
    return {'success': all_success, 'results': results}


# 底部引入 stock_service 以提供命名空间解析（延迟到调用期，避免循环依赖）
from fastapi_app.services import stock_service
