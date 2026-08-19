"""
退货（StockReturn）业务逻辑

包含退货核心 CRUD（*_core）与对外编排函数（create/delete）。

说明：内部对 generate_stockreturn_number / get_product_for_update /
log_inventory_change / publish_stock_event 的引用统一通过 `stock_service.<name>`
解析，以便测试通过 `fastapi_app.services.stock_service.<name>` 打 patch 时能够拦截，
同时保持对外命名空间一致。底部 import 该模块以避免循环依赖。
"""
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.cache_invalidation import cache_mgr
from fastapi_app.core.domain_events import DomainEvent, DomainEventType
from fastapi_app.core.domain_events import publish_with_retry as publish_domain_event
from fastapi_app.core.exception_handler import safe_publish_event
from fastapi_app.core.number_generator import generate_number_async
from fastapi_app.services.notification_service import StockEvent
from fastapi_app.services.stock_common import _parse_date_preserve_time
from fastapi_app.services.stock_event_service import recalc_order_status_after_return
from fastapi_app.shared_models import Product, StockOut, StockReturn

logger = logging.getLogger(__name__)


async def generate_stockreturn_number(db: AsyncSession) -> str:
    """生成退货编号 SR-YYYYMMDD-XXXX"""
    return await generate_number_async('SR', StockReturn, 'return_date', 'return_no', db)


async def create_stockreturn_core(db: AsyncSession, stockout_id: int, quantity: int,
                                  return_date: datetime, reason: str | None = None,
                                  note: str | None = None) -> StockReturn:
    """创建退货记录核心逻辑"""
    if quantity <= 0:
        raise ValueError('退货数量必须大于0')

    stockout_result = await db.execute(select(StockOut).where(StockOut.id == stockout_id).with_for_update())
    stockout = stockout_result.scalar_one_or_none()
    if not stockout:
        raise ValueError('出货记录不存在')
    if stockout.stockin_id is not None:
        raise ValueError('订单抵扣的出货记录不能直接退货！请通过订单管理进行处理。')

    available_return = stockout.quantity - stockout.returned_quantity
    if quantity > available_return:
        raise ValueError(f'退货数量超过可退数量！出货数量：{stockout.quantity}，已退货：{stockout.returned_quantity}，可退：{available_return}')

    return_no = await stock_service.generate_stockreturn_number(db)
    customer = stockout.customer
    order_id = stockout.order_id

    stockreturn = StockReturn(
        return_no=return_no,
        return_date=return_date,
        product_id=stockout.product_id,
        quantity=quantity,
        customer=customer,
        stockout_id=stockout_id,
        order_id=order_id,
        reason=reason,
        note=note,
    )
    db.add(stockreturn)
    await db.flush()

    # 更新出货记录的累计退货量
    stockout.returned_quantity += quantity

    # 恢复库存
    product = await stock_service.get_product_for_update(db, stockout.product_id)
    product.current_stock += quantity

    # 写入库存日志
    stock_service.log_inventory_change(db, product_id=stockout.product_id, change_type='退货', change_quantity=quantity, related_id=str(stockreturn.id), note=f'退货ID：{stockreturn.id}，关联出货ID：{stockout_id}', customer=customer)

    # 重算订单状态（需先flush确保SUM查询读到最新的returned_quantity）
    if order_id:
        await db.flush()
        await recalc_order_status_after_return(db, order_id)

    await db.flush()
    return stockreturn


async def delete_stockreturn_core(db: AsyncSession, stockreturn: StockReturn) -> None:
    """删除退货记录核心逻辑"""
    stockout_result = await db.execute(select(StockOut).where(StockOut.id == stockreturn.stockout_id).with_for_update())
    stockout = stockout_result.scalar_one_or_none()
    if not stockout:
        raise ValueError('关联的出货记录不存在')

    # 回减出货记录的累计退货量
    if stockout.returned_quantity < stockreturn.quantity:
        raise ValueError('退货数量异常：累计退货量小于待删除的退货数量')
    stockout.returned_quantity -= stockreturn.quantity

    # 扣回库存
    product = await stock_service.get_product_for_update(db, stockreturn.product_id)
    if product.current_stock < stockreturn.quantity:
        raise ValueError(f'删除退货将导致库存为负数（当前库存：{product.current_stock}，退货数量：{stockreturn.quantity}）')
    product.current_stock -= stockreturn.quantity

    # 写入库存日志
    stock_service.log_inventory_change(db, product_id=stockreturn.product_id, change_type='退货删除', change_quantity=-stockreturn.quantity, related_id=str(stockreturn.id), note=f'退货删除ID：{stockreturn.id}，关联出货ID：{stockout.id}', customer=stockreturn.customer)

    # 重算订单状态（需先flush确保SUM查询读到最新的returned_quantity）
    if stockreturn.order_id:
        await db.flush()
        await recalc_order_status_after_return(db, stockreturn.order_id)

    await db.delete(stockreturn)
    await db.flush()


async def create_stockreturn(db: AsyncSession, stockout_id: int, quantity: int,
                             return_date_str: str, reason: str | None = None,
                             note: str | None = None) -> dict:
    """创建退货记录"""
    return_date = _parse_date_preserve_time(return_date_str)
    stockreturn = await create_stockreturn_core(db, stockout_id, quantity, return_date, reason, note)
    await db.flush()
    await cache_mgr.invalidate_stock_and_order()
    product = await db.get(Product, stockreturn.product_id)
    if product is not None:
        await safe_publish_event(stock_service.publish_stock_event, StockEvent.STOCK_CHANGED, {'product_id': stockreturn.product_id, 'product_name': product.name, 'change_type': '退货', 'quantity': quantity, 'current_stock': product.current_stock}, context="退货事件发布")

    # 领域事件总线：退货创建 → 发布 STOCK_RETURN_CREATED 事件，触发采购计划重算（异步）
    # 退货会减少已出货量，复用 recalc_plans_after_stockout_delete 逻辑（语义：回滚已分配的出货量）
    stockout = await db.get(StockOut, stockout_id)
    customer_name = stockout.customer if stockout and stockout.customer else ''
    product_name = product.name if product is not None else ''
    plan_month = stockout.stockout_date.strftime('%Y-%m') if stockout and stockout.stockout_date else ''
    await publish_domain_event(DomainEvent(
        event_type=DomainEventType.STOCK_RETURN_CREATED,
        domain='stock',
        payload={
            'product_id': stockreturn.product_id,
            'customer': customer_name,
            'product_name': product_name,
            'stockout_no': stockout.stockout_no if stockout else stockreturn.return_no,
            'deleted_quantity': quantity,
            'plan_month': plan_month,
        },
    ))

    logger.info(f'退货添加成功：{stockreturn.return_no}，关联出货ID：{stockout_id}，数量：{quantity}')
    return {'id': stockreturn.id, 'return_no': stockreturn.return_no}


async def delete_stockreturn(db: AsyncSession, stockreturn_id: int) -> None:
    """删除退货记录"""
    result = await db.execute(select(StockReturn).where(StockReturn.id == stockreturn_id).with_for_update())
    stockreturn_obj = result.scalar_one_or_none()
    if not stockreturn_obj:
        raise ValueError('退货记录不存在')
    return_no = stockreturn_obj.return_no
    deleted_quantity = stockreturn_obj.quantity
    product_id = stockreturn_obj.product_id
    stockout_id = stockreturn_obj.stockout_id
    await delete_stockreturn_core(db, stockreturn_obj)
    await db.flush()
    await cache_mgr.invalidate_stock_and_order()
    product = await db.get(Product, product_id)
    if product is not None:
        await safe_publish_event(stock_service.publish_stock_event, StockEvent.STOCK_CHANGED, {'product_id': product_id, 'product_name': product.name, 'change_type': '退货删除', 'quantity': -deleted_quantity, 'current_stock': product.current_stock}, context="退货删除事件发布")

    # 领域事件总线：退货删除 → 发布 STOCK_RETURN_DELETED 事件，触发采购计划重算（异步）
    # 删除退货会恢复已出货量，复用 recalc_plans_after_stockout_delete 逻辑（语义：回滚退货扣减）
    stockout = await db.get(StockOut, stockout_id)
    customer_name = stockout.customer if stockout and stockout.customer else ''
    product_name = product.name if product is not None else ''
    plan_month = stockout.stockout_date.strftime('%Y-%m') if stockout and stockout.stockout_date else ''
    await publish_domain_event(DomainEvent(
        event_type=DomainEventType.STOCK_RETURN_DELETED,
        domain='stock',
        payload={
            'product_id': product_id,
            'customer': customer_name,
            'product_name': product_name,
            'stockout_no': stockout.stockout_no if stockout else return_no,
            'deleted_quantity': deleted_quantity,
            'plan_month': plan_month,
        },
    ))

    logger.info(f'退货删除成功：{return_no}，数量：{deleted_quantity}')


# 底部引入 stock_service 以提供命名空间解析（延迟到调用期，避免循环依赖）
from fastapi_app.services import stock_service  # noqa: E402
