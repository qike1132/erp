"""
出库（StockOut）业务逻辑

包含出库核心 CRUD（*_core）、对外编排函数（create/update/delete）以及
批量出库（batch_create_stockouts / _validate_stockout_batch /
_create_stockout_records / _process_single_stockout）。

说明：内部对 get_product_for_update / calculate_available_shipment_quantity /
generate_stockout_number / log_inventory_change / publish_stock_event /
同模块 *_core 的引用统一通过 `stock_service.<name>` 解析，
以便测试通过 `fastapi_app.services.stock_service.<name>` 打 patch 时能够拦截，
同时保持对外命名空间一致。底部 import 该模块以避免循环依赖。
"""
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.cache_invalidation import cache_mgr
from fastapi_app.core.domain_events import DomainEvent, DomainEventType
from fastapi_app.core.domain_events import publish_with_retry as publish_domain_event
from fastapi_app.core.exception_handler import safe_publish_event
from fastapi_app.services.notification_service import StockEvent
from fastapi_app.services.stock_common import _parse_date_preserve_time
from fastapi_app.services.stock_event_service import (
    _publish_shipment_completed_events,
    _recalc_shipment_order_statuses,
)
from fastapi_app.shared_models import Product, StockOut

logger = logging.getLogger(__name__)


async def create_stockout_core(db: AsyncSession, product_id: int, quantity: int, customer: str, stockout_date: datetime, note: str, order_type: str='regular', country: str | None=None) -> list[StockOut]:
    product = await stock_service.get_product_for_update(db, product_id)
    if product.current_stock < quantity:
        raise ValueError('库存不足！')
    if order_type == 'custom' and (not country):
        raise ValueError('定制订单必须填写国家名称！')
    shipment_info = await stock_service.calculate_available_shipment_quantity(db, product_id, customer, order_type=order_type, country=country)
    if shipment_info['available_quantity'] <= 0:
        raise ValueError('该客户没有可用的订单支持出货！请先创建订单。')
    if quantity > shipment_info['available_quantity']:
        raise ValueError(f"出货数量超过可出货量！订单总量：{shipment_info['order_quantity']}，已出货：{shipment_info['shipped_quantity']}，可出货：{shipment_info['available_quantity']}")
    remaining_qty = quantity
    created_stockouts: list[StockOut] = []
    async with db.begin_nested():
        for order_detail in shipment_info['orders']:
            if remaining_qty <= 0:
                break
            if order_detail['available'] <= 0:
                continue
            ship_qty = min(remaining_qty, order_detail['available'])
            stockout = StockOut(stockout_no=await stock_service.generate_stockout_number(db), product_id=product_id, quantity=ship_qty, stockout_date=stockout_date, customer=customer, order_id=order_detail['order_id'], note=note)
            db.add(stockout)
            created_stockouts.append(stockout)
            remaining_qty -= ship_qty
        product.current_stock -= quantity
        # 第一次 flush：批量写入所有 StockOut INSERT + Product UPDATE，并填充 stockout.id
        # 原 N 次 flush（N=FIFO订单数）合并为 1 次，减少数据库往返
        await db.flush()
        stock_service.log_inventory_change(db, product_id=product_id, change_type='出库', change_quantity=-quantity, related_id=','.join(str(stock_out.id) for stock_out in created_stockouts) if created_stockouts else '', note=f'出库数量：{quantity}')
        # 第二次 flush：提前暴露 InventoryLog 写入错误（约束违反等），而非依赖 SAVEPOINT 退出时自动 flush
        # 保留原因：错误早暴露便于定位；移除则错误会延迟到 begin_nested 退出时才触发
        await db.flush()
    return created_stockouts


async def update_stockout_core(db: AsyncSession, stockout: StockOut, new_quantity: int, customer: str, stockout_date: datetime, note: str) -> StockOut:
    if stockout.stockin_id is not None:
        raise ValueError('订单抵扣的出货记录不能直接编辑！请通过订单管理进行修改。')
    if new_quantity < stockout.returned_quantity:
        raise ValueError(f'出货数量不能小于已退货数量({stockout.returned_quantity})')
    old_quantity = stockout.quantity
    old_net = old_quantity - stockout.returned_quantity
    product = await stock_service.get_product_for_update(db, stockout.product_id)
    if product.current_stock + old_net < new_quantity - stockout.returned_quantity:
        raise ValueError('库存不足！')
    if customer and customer.strip():
        shipment_info = await stock_service.calculate_available_shipment_quantity(db, stockout.product_id, customer)
        available_with_current = shipment_info['available_quantity'] + old_net
        if new_quantity - stockout.returned_quantity > available_with_current:
            raise ValueError(f"出货数量超过可出货量！订单总量：{shipment_info['order_quantity']}，可出货（含当前记录）：{available_with_current}")
    stockout.quantity = new_quantity
    stockout.stockout_date = stockout_date
    stockout.customer = customer
    stockout.note = note
    if new_quantity != old_quantity:
        product.current_stock -= new_quantity - old_quantity
        stock_service.log_inventory_change(db, product_id=stockout.product_id, change_type='出库修改', change_quantity=-(new_quantity - old_quantity), related_id=str(stockout.id), note=f'出库修改ID：{stockout.id}')
    await db.flush()
    return stockout


async def delete_stockout_core(db: AsyncSession, stockout: StockOut) -> None:
    if stockout.stockin_id is not None:
        raise ValueError('订单抵扣的出货记录不能直接删除！请通过订单管理进行修改。')
    if stockout.returned_quantity > 0:
        raise ValueError('该出货记录已有退货关联，无法删除！请先删除退货记录。')
    product = await stock_service.get_product_for_update(db, stockout.product_id)
    product.current_stock += stockout.quantity
    stock_service.log_inventory_change(db, product_id=stockout.product_id, change_type='出库删除', change_quantity=stockout.quantity, related_id=str(stockout.id), note=f'出库删除ID：{stockout.id}')
    await db.delete(stockout)
    await db.flush()


async def create_stockout(db: AsyncSession, product_id: int, quantity: int, customer: str, stockout_date_str: str, note: str, order_type: str='regular', country: str | None=None) -> dict:
    """创建出库记录"""
    stockout_date = _parse_date_preserve_time(stockout_date_str)
    created_stockouts = await stock_service.create_stockout_core(db, product_id, quantity, customer, stockout_date, note, order_type, country)
    shipment_completed_orders = await _recalc_shipment_order_statuses(db, created_stockouts)

    await db.flush()
    await cache_mgr.invalidate_stock_and_order()
    product = await db.get(Product, product_id)
    if product is not None:
        await safe_publish_event(stock_service.publish_stock_event, StockEvent.STOCK_CHANGED, {'product_id': product_id, 'product_name': product.name, 'change_type': '出库', 'quantity': quantity, 'current_stock': product.current_stock}, context="出库事件发布")

    await _publish_shipment_completed_events(shipment_completed_orders)

    # 领域事件总线：出库单创建 → 发布 STOCK_OUT_CREATED 事件，供跨域订阅者消费
    # 采购计划重算与缓存失效由 purchase_plan_service 的事件处理器异步执行，解耦循环依赖
    # publish_with_retry 内部已处理重试与错误日志，无需外层 try/except
    plan_month = stockout_date.strftime('%Y-%m') if stockout_date else ''
    product_name = product.name if product is not None else ''
    await publish_domain_event(DomainEvent(
        event_type=DomainEventType.STOCK_OUT_CREATED,
        domain='stock',
        payload={
            'product_id': product_id,
            'quantity': quantity,
            'customer': customer,
            'product_name': product_name,
            'plan_month': plan_month,
        },
    ))

    logger.info(f'出库添加成功：产品ID：{product_id}，数量：{quantity}，客户：{customer}')
    return {'quantity': quantity}


async def update_stockout(db: AsyncSession, stockout_id: int, new_quantity: int, customer: str, stockout_date_str: str, note: str) -> None:
    """更新出库记录"""
    pid_result = await db.execute(select(StockOut.product_id).where(StockOut.id == stockout_id))
    pid_row = pid_result.one_or_none()
    if not pid_row:
        raise ValueError('出库记录不存在')
    await stock_service.get_product_for_update(db, pid_row[0])
    result = await db.execute(select(StockOut).where(StockOut.id == stockout_id).with_for_update())
    stockout_obj = result.scalar_one_or_none()
    if not stockout_obj:
        raise ValueError('出库记录不存在')
    stockout_date = _parse_date_preserve_time(stockout_date_str)
    old_quantity = stockout_obj.quantity
    old_stockout_no = stockout_obj.stockout_no
    await update_stockout_core(db, stockout_obj, new_quantity, customer, stockout_date, note)
    await db.flush()
    await cache_mgr.invalidate_stock_and_order()
    product = await db.get(Product, stockout_obj.product_id)
    if product is not None:
        await safe_publish_event(stock_service.publish_stock_event, StockEvent.STOCK_CHANGED, {'product_id': stockout_obj.product_id, 'product_name': product.name, 'change_type': '出库编辑', 'quantity': new_quantity, 'current_stock': product.current_stock}, context="出库编辑事件发布")

    # 领域事件总线：出库单更新 → 发布 STOCK_OUT_UPDATED 事件，触发采购计划缓存失效（异步）
    plan_month = stockout_obj.stockout_date.strftime('%Y-%m') if stockout_obj.stockout_date else ''
    await publish_domain_event(DomainEvent(
        event_type=DomainEventType.STOCK_OUT_UPDATED,
        domain='stock',
        payload={
            'product_id': stockout_obj.product_id,
            'customer': customer,
            'product_name': product.name if product is not None else '',
            'plan_month': plan_month,
        },
    ))

    logger.info(f'出库编辑成功：{old_stockout_no}，数量变更：{old_quantity} -> {new_quantity}')


async def delete_stockout(db: AsyncSession, stockout_id: int) -> None:
    """删除出库记录"""
    result = await db.execute(select(StockOut).where(StockOut.id == stockout_id).with_for_update())
    stockout_obj = result.scalar_one_or_none()
    if not stockout_obj:
        raise ValueError('出库记录不存在')
    stockout_no = stockout_obj.stockout_no
    deleted_quantity = stockout_obj.quantity
    customer_name = stockout_obj.customer or ''
    product_result = await db.execute(select(Product.name).where(Product.id == stockout_obj.product_id))
    product_name_row = product_result.one_or_none()
    product_name = product_name_row[0] if product_name_row else ''
    await stock_service.delete_stockout_core(db, stockout_obj)
    await db.flush()
    await cache_mgr.invalidate_stock_and_order()
    product = await db.get(Product, stockout_obj.product_id)
    if product is not None:
        await safe_publish_event(stock_service.publish_stock_event, StockEvent.STOCK_CHANGED, {'product_id': stockout_obj.product_id, 'product_name': product.name, 'change_type': '出库删除', 'quantity': -deleted_quantity, 'current_stock': product.current_stock}, context="出库删除事件发布")

    # 领域事件总线：出库单删除 → 发布 STOCK_OUT_DELETED 事件，触发采购计划重算与缓存失效（异步）
    plan_month = stockout_obj.stockout_date.strftime('%Y-%m') if stockout_obj.stockout_date else ''
    await publish_domain_event(DomainEvent(
        event_type=DomainEventType.STOCK_OUT_DELETED,
        domain='stock',
        payload={
            'product_id': stockout_obj.product_id,
            'customer': customer_name,
            'product_name': product_name,
            'stockout_no': stockout_no,
            'deleted_quantity': deleted_quantity,
            'plan_month': plan_month,
        },
    ))

    logger.info(f'出库删除成功：{stockout_no}，数量：{deleted_quantity}')


def _validate_stockout_batch(stockouts_data: list) -> tuple[list, dict]:
    """校验批量出库数据，返回 (有效项 (idx, item) 列表, 错误映射)"""
    validated = []
    errors_map = {}
    for idx, item in enumerate(stockouts_data):
        product_id = item.get('product_id')
        customer = str(item.get('customer', '')).strip()
        quantity = item.get('quantity', 0)
        order_type = item.get('order_type', 'regular') or 'regular'
        country = item.get('country', '') or ''
        if not all([product_id, quantity]):
            errors_map[idx] = '缺少必填字段'
            continue
        if not customer:
            errors_map[idx] = '出货必须选择客户'
            continue
        if order_type == 'custom' and (not country):
            errors_map[idx] = '定制订单必须填写国家名称'
            continue
        if int(quantity) <= 0:
            errors_map[idx] = '出货数量必须大于0'
            continue
        validated.append((idx, item))
    return validated, errors_map


async def _create_stockout_records(db: AsyncSession, product_id: int, customer: str,
                                   note: str, stockout_date_str: str, quantity: int,
                                   orders: list) -> list[StockOut]:
    """按 FIFO 分配订单，创建出库记录"""
    remaining_qty = quantity
    created_stockouts: list[StockOut] = []
    for order_detail in orders:
        if remaining_qty <= 0:
            break
        if order_detail['available'] <= 0:
            continue
        ship_qty = min(remaining_qty, order_detail['available'])
        stockout_no = await stock_service.generate_stockout_number(db)
        stockout = StockOut(
            stockout_no=stockout_no, product_id=product_id, quantity=ship_qty,
            stockout_date=(_parse_date_preserve_time(stockout_date_str).replace(tzinfo=UTC) if stockout_date_str else datetime.now(UTC)),
            customer=customer, order_id=order_detail['order_id'], note=note
        )
        db.add(stockout)
        created_stockouts.append(stockout)
        remaining_qty -= ship_qty
    # 单次 flush：批量写入所有 StockOut INSERT 并填充 id，供调用方构建 related_id
    # 原 N 次 flush（N=FIFO订单数）合并为 1 次
    if created_stockouts:
        await db.flush()
    return created_stockouts


async def _process_single_stockout(db: AsyncSession, item: dict) -> dict:
    """处理单条出库记录的创建（含库存校验、订单分配、库存扣减）"""
    product_id = item.get('product_id')
    customer = str(item.get('customer', '')).strip()
    quantity = int(item.get('quantity', 0))
    order_type = item.get('order_type', 'regular') or 'regular'
    country = item.get('country', '') or None
    note = item.get('note', '')
    stockout_date_str = item.get('stockout_date') or ''
    item_id = item.get('id', '未知')
    try:
        product = await stock_service.get_product_for_update(db, product_id)
        if product.current_stock < quantity:
            return {'success': False, 'error': f'库存不足，当前库存: {product.current_stock}', 'id': item_id}

        shipment_info = await stock_service.calculate_available_shipment_quantity(db, product_id, customer, order_type=order_type, country=country)
        if shipment_info['available_quantity'] <= 0:
            return {'success': False, 'error': '该客户没有可用的订单支持出货！请先创建订单。', 'id': item_id}
        if quantity > shipment_info['available_quantity']:
            return {'success': False, 'error': f"出货数量超过可出货量！订单总量：{shipment_info['order_quantity']}，已出货：{shipment_info['shipped_quantity']}，可出货：{shipment_info['available_quantity']}", 'id': item_id}

        created_stockouts = await _create_stockout_records(db, product_id, customer, note, stockout_date_str, quantity, shipment_info['orders'])
        product.current_stock -= quantity
        stock_service.log_inventory_change(db, product_id=product_id, change_type='出库', change_quantity=-quantity, related_id=','.join(str(stockout.id) for stockout in created_stockouts) if created_stockouts else '', note=f'出库数量：{quantity}')
        await db.flush()

        stockout_nos = [stockout.stockout_no for stockout in created_stockouts] if created_stockouts else []
        return {'success': True, 'stockout_no': stockout_nos[0] if stockout_nos else '', 'id': item_id}
    except ValueError as e:
        return {'success': False, 'error': str(e), 'id': item_id}
    except (TypeError, OSError) as e:
        logger.error(f'批量出库单项失败: {e}', exc_info=True)
        return {'success': False, 'error': str(e) or '出库处理失败，请稍后重试', 'id': item_id}


async def batch_create_stockouts(db: AsyncSession, stockouts_data: list) -> dict:
    """批量创建出库记录（自包含，不调用 create_stockout_core，无嵌套事务）"""
    validated, errors_map = _validate_stockout_batch(stockouts_data)
    results = [None] * len(stockouts_data)
    for idx, err in errors_map.items():
        results[idx] = {'success': False, 'error': err, 'id': stockouts_data[idx].get('id', '未知')}
    for orig_idx, item in validated:
        results[orig_idx] = await _process_single_stockout(db, item)
    all_success = all(result is not None and result.get('success') for result in results)
    return {'success': all_success, 'results': results}


# 底部引入 stock_service 以提供命名空间解析（延迟到调用期，避免循环依赖）
from fastapi_app.services import stock_service  # noqa: E402
