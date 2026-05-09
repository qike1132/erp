"""
库存管理业务逻辑服务

核心 CRUD 和库存计算已统一至 fastapi_app.shared.stock_crud_service。
本服务负责异步适配层：将同步 shared 函数包装为异步调用，
并处理事件发布等 FastAPI 特有逻辑。
"""
import contextlib
import logging
from datetime import UTC, datetime

from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from fastapi_app.core.cache import cache_result, invalidate_cache
from fastapi_app.services import escape_like
from fastapi_app.services.batch_service import (
    calculate_available_shipment_quantity,
    generate_stockin_number,
    generate_stockout_number,
)
from fastapi_app.services.notification_service import StockEvent, publish_stock_event
from fastapi_app.shared.stock_concurrency import get_product_for_update
from fastapi_app.shared_models import InventoryLog, Product, StockIn, StockOut, StockReturn

logger = logging.getLogger(__name__)

async def create_stockin_core(db: AsyncSession, product_id: int, quantity: int, customer: str, stockin_date: datetime, note: str, order_type: str = 'regular', country: str | None = None) -> StockIn:
    if quantity <= 0:
        raise ValueError('入库数量必须大于0')
    stockin = StockIn(stockin_no=await generate_stockin_number(db), product_id=product_id, quantity=quantity, customer=customer, stockin_date=stockin_date, note=note, order_type=order_type, country=country)
    db.add(stockin)
    await db.flush()
    product = await get_product_for_update(db, product_id)
    product.current_stock += quantity
    db.add(InventoryLog(product_id=product_id, change_type='入库', change_quantity=quantity, related_id=str(stockin.id), note=f'入库ID：{stockin.id}'))
    await db.flush()
    return stockin

async def update_stockin_core(db: AsyncSession, stockin: StockIn, quantity: int, customer: str, stockin_date: datetime, note: str, order_type: str = 'regular', country: str | None = None) -> StockIn:
    old_quantity = stockin.quantity
    stockin.quantity = quantity
    stockin.customer = customer
    stockin.stockin_date = stockin_date
    stockin.note = note
    stockin.order_type = order_type
    stockin.country = country
    if quantity != old_quantity:
        product = await get_product_for_update(db, stockin.product_id)
        product.current_stock += quantity - old_quantity
        db.add(InventoryLog(product_id=stockin.product_id, change_type='入库修改', change_quantity=quantity - old_quantity, related_id=str(stockin.id), note=f'入库修改ID：{stockin.id}'))
    await db.flush()
    return stockin

async def delete_stockin_core(db: AsyncSession, stockin: StockIn) -> None:
    if stockin.stockin_stockouts:
        raise ValueError('该入库记录已有出库关联，无法删除')
    product = await get_product_for_update(db, stockin.product_id)
    if product.current_stock - stockin.quantity < 0:
        raise ValueError(f'删除入库记录将导致库存为负数（产品：{product.name}，当前库存：{product.current_stock}，入库数量：{stockin.quantity}）')
    product.current_stock -= stockin.quantity
    db.add(InventoryLog(product_id=stockin.product_id, change_type='入库删除', change_quantity=-stockin.quantity, related_id=str(stockin.id), note=f'入库删除ID：{stockin.id}'))
    await db.delete(stockin)
    await db.flush()

async def create_stockout_core(db: AsyncSession, product_id: int, quantity: int, customer: str, stockout_date: datetime, note: str, order_type: str='regular', country: str | None=None) -> list[StockOut]:
    product = await get_product_for_update(db, product_id)
    if product.current_stock < quantity:
        raise ValueError('库存不足！')
    if order_type == 'custom' and (not country):
        raise ValueError('定制订单必须填写国家名称！')
    shipment_info = await calculate_available_shipment_quantity(db, product_id, customer, order_type=order_type, country=country)
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
            stockout = StockOut(stockout_no=await generate_stockout_number(db), product_id=product_id, quantity=ship_qty, stockout_date=stockout_date, customer=customer, order_id=order_detail['order_id'], note=note)
            db.add(stockout)
            await db.flush()
            created_stockouts.append(stockout)
            remaining_qty -= ship_qty
        product.current_stock -= quantity
        db.add(InventoryLog(product_id=product_id, change_type='出库', change_quantity=-quantity, related_id=','.join(str(s.id) for s in created_stockouts) if created_stockouts else '', note=f'出库数量：{quantity}'))
        await db.flush()
    return created_stockouts

async def update_stockout_core(db: AsyncSession, stockout: StockOut, new_quantity: int, customer: str, stockout_date: datetime, note: str) -> StockOut:
    if stockout.stockin_id is not None:
        raise ValueError('订单抵扣的出货记录不能直接编辑！请通过订单管理进行修改。')
    if new_quantity < stockout.returned_quantity:
        raise ValueError(f'出货数量不能小于已退货数量({stockout.returned_quantity})')
    old_quantity = stockout.quantity
    old_net = old_quantity - stockout.returned_quantity
    product = await get_product_for_update(db, stockout.product_id)
    if product.current_stock + old_net < new_quantity - stockout.returned_quantity:
        raise ValueError('库存不足！')
    if customer and customer.strip():
        shipment_info = await calculate_available_shipment_quantity(db, stockout.product_id, customer)
        available_with_current = shipment_info['available_quantity'] + old_net
        if new_quantity - stockout.returned_quantity > available_with_current:
            raise ValueError(f"出货数量超过可出货量！订单总量：{shipment_info['order_quantity']}，可出货（含当前记录）：{available_with_current}")
    stockout.quantity = new_quantity
    stockout.stockout_date = stockout_date
    stockout.customer = customer
    stockout.note = note
    if new_quantity != old_quantity:
        product.current_stock -= new_quantity - old_quantity
        db.add(InventoryLog(product_id=stockout.product_id, change_type='出库修改', change_quantity=-(new_quantity - old_quantity), related_id=str(stockout.id), note=f'出库修改ID：{stockout.id}'))
    await db.flush()
    return stockout

async def delete_stockout_core(db: AsyncSession, stockout: StockOut) -> None:
    if stockout.stockin_id is not None:
        raise ValueError('订单抵扣的出货记录不能直接删除！请通过订单管理进行修改。')
    if stockout.returned_quantity > 0:
        raise ValueError('该出货记录已有退货关联，无法删除！请先删除退货记录。')
    product = await get_product_for_update(db, stockout.product_id)
    product.current_stock += stockout.quantity
    db.add(InventoryLog(product_id=stockout.product_id, change_type='出库删除', change_quantity=stockout.quantity, related_id=str(stockout.id), note=f'出库删除ID：{stockout.id}'))
    await db.delete(stockout)
    await db.flush()


async def generate_stockreturn_number(db: AsyncSession) -> str:
    """生成退货编号 SR-YYYYMMDD-XXXX"""
    from fastapi_app.shared.stock_crud_service import SyncNumberGenerator
    today = datetime.now(UTC)
    date_str = today.strftime('%Y%m%d')
    prefix = 'SR'
    result = await db.execute(
        select(StockReturn)
        .where(func.date(StockReturn.return_date) == today.date())
        .order_by(StockReturn.return_no.desc())
        .limit(1)
        .with_for_update()
    )
    record = result.scalar_one_or_none()
    db_max = 0
    if record:
        with contextlib.suppress(ValueError, IndexError):
            db_max = int(record.return_no.split('-')[-1])
    generator = SyncNumberGenerator()
    with generator._lock:
        generator._cleanup_old_entries()
        current_seq = max(db_max, generator._counters.get(f"{prefix}:{date_str}", 0)) + 1
        generator._counters[f"{prefix}:{date_str}"] = current_seq
    return f"{prefix}-{date_str}-{str(current_seq).zfill(4)}"


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

    return_no = await generate_stockreturn_number(db)
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
    product = await get_product_for_update(db, stockout.product_id)
    product.current_stock += quantity

    # 写入库存日志
    db.add(InventoryLog(
        product_id=stockout.product_id,
        change_type='退货',
        change_quantity=quantity,
        related_id=str(stockreturn.id),
        note=f'退货ID：{stockreturn.id}，关联出货ID：{stockout_id}',
        customer=customer,
    ))

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
    product = await get_product_for_update(db, stockreturn.product_id)
    if product.current_stock < stockreturn.quantity:
        raise ValueError(f'删除退货将导致库存为负数（当前库存：{product.current_stock}，退货数量：{stockreturn.quantity}）')
    product.current_stock -= stockreturn.quantity

    # 写入库存日志
    db.add(InventoryLog(
        product_id=stockreturn.product_id,
        change_type='退货删除',
        change_quantity=-stockreturn.quantity,
        related_id=str(stockreturn.id),
        note=f'退货删除ID：{stockreturn.id}，关联出货ID：{stockout.id}',
        customer=stockreturn.customer,
    ))

    # 重算订单状态（需先flush确保SUM查询读到最新的returned_quantity）
    if stockreturn.order_id:
        await db.flush()
        await recalc_order_status_after_return(db, stockreturn.order_id)

    await db.delete(stockreturn)
    await db.flush()


async def recalc_order_status_after_return(db: AsyncSession, order_id: int) -> None:
    """
    退货后重算订单状态（派生计算）

    根据订单关联的实际出入库数据推导状态，无需手动维护状态流转。
    """
    from fastapi_app.shared_models import Order
    order_result = await db.execute(select(Order).where(Order.id == order_id).with_for_update())
    order = order_result.scalar_one_or_none()
    if not order:
        return
    if order.status in (None, '已取消'):
        return

    from fastapi_app.services.order_service import compute_order_status_from_db
    order.status = await compute_order_status_from_db(db, order)

async def get_stockins(db: AsyncSession, page: int=1, per_page: int=50) -> dict:
    """获取入库列表（含关联数据，支持分页）- SQL子查询优化版"""
    total = (await db.execute(select(func.count(StockIn.id)))).scalar() or 0
    # 使用 SQL 子查询计算已抵扣数量，避免 Python 层遍历 stockin_stockouts
    deducted_sub = (
        select(
            StockOut.stockin_id.label('sid'),
            func.coalesce(func.sum(StockOut.quantity - StockOut.returned_quantity), 0).label('deducted')
        )
        .where(StockOut.stockin_id.isnot(None))
        .group_by(StockOut.stockin_id)
        .subquery()
    )
    result = await db.execute(
        select(StockIn, func.coalesce(deducted_sub.c.deducted, 0).label('deducted'))
        .outerjoin(deducted_sub, StockIn.id == deducted_sub.c.sid)
        .options(joinedload(StockIn.product))
        .order_by(StockIn.stockin_date.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    data = []
    for row in result.all():
        s = row.StockIn
        deducted = int(row.deducted) if row.deducted is not None else 0
        data.append({
            'id': s.id, 'stockin_no': s.stockin_no,
            'stockin_date': s.stockin_date.strftime('%Y-%m-%d') if s.stockin_date else '',
            'customer': s.customer,
            'product': {'id': s.product.id, 'name': s.product.name, 'barcode': s.product.barcode or '', 'image': s.product.image or ''} if s.product else None,
            'quantity': s.quantity,
            'order_type': s.order_type or 'regular',
            'country': s.country or '',
            'deducted': deducted,
            'note': s.note or '',
        })
    return {'items': data, 'total': total, 'page': page, 'per_page': per_page}

async def create_stockin(db: AsyncSession, product_id: int, quantity: int, customer: str, stockin_date_str: str, note: str) -> dict:
    """创建入库记录"""
    stockin_date = _parse_date_preserve_time(stockin_date_str)
    try:
        stockin = await create_stockin_core(db, product_id, quantity, customer, stockin_date, note)
        await db.commit()
    except (SQLAlchemyError, ValueError):
        await db.rollback()
        raise
    await invalidate_cache('inventory:*')
    await invalidate_cache('orders:*')
    try:
        product = await db.get(Product, product_id)
        if product is None:
            logger.warning(f'入库事件发布失败：产品ID {product_id} 不存在')
        else:
            await publish_stock_event(StockEvent.STOCK_CHANGED, {'product_id': product_id, 'product_name': product.name, 'change_type': '入库', 'quantity': quantity, 'current_stock': product.current_stock})
    except (OSError, ConnectionError, ValueError) as e:
        logger.warning(f'入库事件发布失败（不影响数据）: {e}')
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
    try:
        await update_stockin_core(db, stockin_obj, quantity, customer, stockin_date, note)
        await db.commit()
    except (SQLAlchemyError, ValueError):
        await db.rollback()
        raise
    await invalidate_cache('inventory:*')
    await invalidate_cache('orders:*')
    logger.info(f'入库编辑成功：{old_stockin_no}，数量变更：{old_quantity} -> {quantity}')

async def delete_stockin(db: AsyncSession, stockin_id: int) -> None:
    """删除入库记录"""
    result = await db.execute(select(StockIn).where(StockIn.id == stockin_id).options(selectinload(StockIn.stockin_stockouts)).with_for_update())
    stockin_obj = result.scalar_one_or_none()
    if not stockin_obj:
        raise ValueError('入库记录不存在')
    stockin_no = stockin_obj.stockin_no
    try:
        await delete_stockin_core(db, stockin_obj)
        await db.commit()
    except (SQLAlchemyError, ValueError):
        await db.rollback()
        raise
    await invalidate_cache('inventory:*')
    await invalidate_cache('orders:*')
    logger.info(f'入库删除成功：{stockin_no}，数量：{stockin_obj.quantity}')

async def get_stockouts(db: AsyncSession, page: int=1, per_page: int=50) -> dict:
    """获取出库列表（仅独立出库，非抵扣，支持分页）"""
    base_condition = StockOut.stockin_id.is_(None)
    base_query = select(StockOut).where(base_condition)
    total = (await db.execute(select(func.count(StockOut.id)).where(base_condition))).scalar() or 0
    result = await db.execute(base_query.options(joinedload(StockOut.product), joinedload(StockOut.order)).order_by(StockOut.stockout_date.desc()).offset((page - 1) * per_page).limit(per_page))
    stockouts = result.scalars().unique().all()
    data = []
    for s in stockouts:
        data.append({'id': s.id, 'stockout_no': s.stockout_no, 'stockout_date': s.stockout_date.strftime('%Y-%m-%d') if s.stockout_date else '', 'customer': s.customer, 'product': {'id': s.product.id, 'name': s.product.name, 'barcode': s.product.barcode or '', 'image': s.product.image or ''} if s.product else None, 'quantity': s.quantity, 'returned_quantity': s.returned_quantity, 'note': s.note or '', 'order_type': s.order.order_type if s.order else 'regular', 'country': s.order.country if s.order and s.order.country else ''})
    return {'items': data, 'total': total, 'page': page, 'per_page': per_page}

async def create_stockout(db: AsyncSession, product_id: int, quantity: int, customer: str, stockout_date_str: str, note: str, order_type: str='regular', country: str | None=None) -> dict:
    """创建出库记录"""
    stockout_date = _parse_date_preserve_time(stockout_date_str)
    try:
        await create_stockout_core(db, product_id, quantity, customer, stockout_date, note, order_type, country)
        await db.commit()
    except (SQLAlchemyError, ValueError):
        await db.rollback()
        raise
    await invalidate_cache('inventory:*')
    await invalidate_cache('orders:*')
    try:
        product = await db.get(Product, product_id)
        if product is not None:
            await publish_stock_event(StockEvent.STOCK_CHANGED, {'product_id': product_id, 'product_name': product.name, 'change_type': '出库', 'quantity': quantity, 'current_stock': product.current_stock})
    except (OSError, ConnectionError, ValueError) as e:
        logger.warning(f'出库事件发布失败（不影响数据）: {e}')
    logger.info(f'出库添加成功：产品ID：{product_id}，数量：{quantity}，客户：{customer}')
    return {'quantity': quantity}

async def update_stockout(db: AsyncSession, stockout_id: int, new_quantity: int, customer: str, stockout_date_str: str, note: str) -> None:
    """更新出库记录"""
    result = await db.execute(select(StockOut).where(StockOut.id == stockout_id).with_for_update())
    stockout_obj = result.scalar_one_or_none()
    if not stockout_obj:
        raise ValueError('出库记录不存在')
    stockout_date = _parse_date_preserve_time(stockout_date_str)
    old_quantity = stockout_obj.quantity
    old_stockout_no = stockout_obj.stockout_no
    try:
        await update_stockout_core(db, stockout_obj, new_quantity, customer, stockout_date, note)
        await db.commit()
    except (SQLAlchemyError, ValueError):
        await db.rollback()
        raise
    await invalidate_cache('inventory:*')
    await invalidate_cache('orders:*')
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
    try:
        await delete_stockout_core(db, stockout_obj)
        if customer_name and product_name:
            from fastapi_app.services.purchase_plan_service import recalc_plans_after_stockout_delete
            await recalc_plans_after_stockout_delete(
                db, customer_name, product_name, stockout_no, deleted_quantity,
            )
        await db.commit()
    except (SQLAlchemyError, ValueError):
        await db.rollback()
        raise
    await invalidate_cache('inventory:*')
    await invalidate_cache('orders:*')
    logger.info(f'出库删除成功：{stockout_no}，数量：{deleted_quantity}')

async def create_stockreturn(db: AsyncSession, stockout_id: int, quantity: int,
                             return_date_str: str, reason: str | None = None,
                             note: str | None = None) -> dict:
    """创建退货记录"""
    return_date = _parse_date_preserve_time(return_date_str)
    try:
        stockreturn = await create_stockreturn_core(db, stockout_id, quantity, return_date, reason, note)
        # 采购计划重算
        stockout = await db.get(StockOut, stockout_id)
        if stockout and stockout.customer:
            product_result = await db.execute(select(Product.name).where(Product.id == stockout.product_id))
            product_name_row = product_result.one_or_none()
            product_name = product_name_row[0] if product_name_row else ''
            if product_name:
                from fastapi_app.services.purchase_plan_service import recalc_plans_after_stockout_delete
                await recalc_plans_after_stockout_delete(
                    db, stockout.customer, product_name, stockreturn.return_no, quantity,
                )
        await db.commit()
    except (SQLAlchemyError, ValueError):
        await db.rollback()
        raise
    await invalidate_cache('inventory:*')
    await invalidate_cache('orders:*')
    try:
        product = await db.get(Product, stockreturn.product_id)
        if product is not None:
            await publish_stock_event(StockEvent.STOCK_CHANGED, {'product_id': stockreturn.product_id, 'product_name': product.name, 'change_type': '退货', 'quantity': quantity, 'current_stock': product.current_stock})
    except (OSError, ConnectionError, ValueError) as e:
        logger.warning(f'退货事件发布失败（不影响数据）: {e}')
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
    try:
        await delete_stockreturn_core(db, stockreturn_obj)
        # 采购计划重算
        stockout = await db.get(StockOut, stockout_id)
        if stockout and stockout.customer:
            product_result = await db.execute(select(Product.name).where(Product.id == stockout.product_id))
            product_name_row = product_result.one_or_none()
            product_name = product_name_row[0] if product_name_row else ''
            if product_name:
                from fastapi_app.services.purchase_plan_service import recalc_plans_after_stockout_delete
                await recalc_plans_after_stockout_delete(
                    db, stockout.customer, product_name, return_no, deleted_quantity,
                )
        await db.commit()
    except (SQLAlchemyError, ValueError):
        await db.rollback()
        raise
    await invalidate_cache('inventory:*')
    await invalidate_cache('orders:*')
    try:
        product = await db.get(Product, product_id)
        if product is not None:
            await publish_stock_event(StockEvent.STOCK_CHANGED, {'product_id': product_id, 'product_name': product.name, 'change_type': '退货删除', 'quantity': -deleted_quantity, 'current_stock': product.current_stock})
    except (OSError, ConnectionError, ValueError) as e:
        logger.warning(f'退货删除事件发布失败（不影响数据）: {e}')
    logger.info(f'退货删除成功：{return_no}，数量：{deleted_quantity}')

async def get_stockreturns(db: AsyncSession, stockout_id: int | None = None,
                           page: int = 1, per_page: int = 50) -> dict:
    """获取退货列表（支持按出货ID筛选，支持分页）"""
    query = select(StockReturn)
    if stockout_id:
        query = query.where(StockReturn.stockout_id == stockout_id)
    total = (await db.execute(select(func.count(StockReturn.id)).where(StockReturn.stockout_id == stockout_id if stockout_id else True))).scalar() or 0
    result = await db.execute(
        query.options(joinedload(StockReturn.product), joinedload(StockReturn.stockout))
        .order_by(StockReturn.return_date.desc())
        .offset((page - 1) * per_page).limit(per_page)
    )
    returns = result.scalars().unique().all()
    data = []
    for r in returns:
        data.append({
            'id': r.id,
            'return_no': r.return_no,
            'return_date': r.return_date.strftime('%Y-%m-%d') if r.return_date else '',
            'product': {'id': r.product.id, 'name': r.product.name} if r.product else None,
            'quantity': r.quantity,
            'customer': r.customer,
            'stockout_id': r.stockout_id,
            'stockout_no': r.stockout.stockout_no if r.stockout else '',
            'reason': r.reason or '',
            'note': r.note or '',
        })
    return {'items': data, 'total': total, 'page': page, 'per_page': per_page}

@cache_result(key_prefix='inventory', ttl=60, local_ttl=30, key_builder=lambda *args, **kwargs: f"c{kwargs.get('search_customer', '')}:p{kwargs.get('search_product', '')}")
async def get_inventory(db: AsyncSession, search_customer: str='', search_product: str='') -> dict:
    """
    获取库存数据（按产品+客户维度汇总）- SQL聚合优化版
    目标：O(P*C*S) 内存聚合 → SQL GROUP BY，响应时间降低 50-80%
    """
    product_ids = await _resolve_products(db, search_product)
    if not product_ids:
        return {'inventory_data': [], 'total_order_qty': 0, 'total_stockin_qty': 0, 'total_stock': 0, 'all_countries': []}
    rows = await _fetch_inventory(db, product_ids, search_customer)
    if not rows:
        return {'inventory_data': [], 'total_order_qty': 0, 'total_stockin_qty': 0, 'total_stock': 0, 'all_countries': []}
    all_countries = set()
    total_stockin_qty = 0
    total_order_qty = 0
    total_stock = 0
    inventory_data = []
    for row in rows:
        customer = row['customer']
        pname = row.get('product_name', '')
        pbarcode = row.get('product_barcode') or ''
        si_qty = int(row.get('stockin_qty') or 0)
        so_dir = int(row.get('direct_stockout_qty') or 0)
        so_reg = int(row.get('regular_stockout_qty') or 0)
        so_cus = int(row.get('custom_stockout_qty') or 0)
        o_reg = int(row.get('regular_order_qty') or 0)
        o_cus = int(row.get('custom_order_qty') or 0)
        has_si = bool(row.get('has_stockin'))
        has_o = bool(row.get('has_order'))
        so_total = so_dir + so_reg + so_cus
        remaining_reg = max(0, o_reg - so_dir - so_reg)
        remaining_cus = max(0, o_cus - so_cus)
        total_qty = si_qty + remaining_reg + remaining_cus
        has_positive = total_qty > 0
        country_data = {}
        raw = row.get('country_data') or ''
        if raw:
            for item in raw.split('|'):
                if ':' in item:
                    c, q = item.split(':', 1)
                    qty = int(q)
                    country_data[c] = qty
                    if c != '常规':
                        all_countries.add(c)
        if (has_si or has_o) and has_positive:
            inventory_data.append({'customer': customer, 'product_name': pname, 'product_barcode': pbarcode, 'order_quantity': remaining_reg if remaining_reg > 0 else '', 'country_orders': country_data, 'stockin_quantity': si_qty if si_qty > 0 else '', 'stockout_quantity': so_total if so_total > 0 else '', 'total_stock': total_qty if total_qty > 0 else ''})
            total_stockin_qty += si_qty
            total_order_qty += remaining_reg + remaining_cus
            total_stock += total_qty
    return {'inventory_data': inventory_data, 'total_order_qty': total_order_qty, 'total_stockin_qty': total_stockin_qty, 'total_stock': total_stock, 'all_countries': sorted(all_countries)}


async def get_inventory_paginated(db: AsyncSession, search_customer: str = '', search_product: str = '',
                                  country: str = '', page: int = 1, per_page: int = 50) -> dict:
    """
    库存分页查询 - SQL CTE 优化版
    将4次聚合查询合并为单次 CTE 查询，在数据库层面完成合并、过滤和分页，
    避免加载全量数据到 Python 内存。20K+ 条数据时响应时间从秒级降至百毫秒级。
    """
    product_ids = await _resolve_products(db, search_product)
    if not product_ids:
        return _empty_inventory_response(page, per_page)

    pids_param = tuple(product_ids)
    params: dict = {'pids': pids_param}
    cust_clause = ''
    if search_customer:
        params['sc'] = search_customer
        cust_clause = " AND customer = :sc"

    # 单次 CTE 查询：合并4个聚合子查询 → 过滤 → 统计 → 分页
    cte_sql = text(f"""
WITH stockin_agg AS (
    SELECT si.product_id, si.customer,
           SUM(si.quantity - COALESCE(sub.consumed, 0)) AS stockin_qty,
           1 AS has_stockin
    FROM stock_in si
    LEFT JOIN (
        SELECT stockin_id, SUM(quantity - returned_quantity) AS consumed
        FROM stock_out WHERE stockin_id IS NOT NULL AND product_id = ANY(:pids)
        GROUP BY stockin_id
    ) sub ON sub.stockin_id = si.id
    WHERE si.product_id = ANY(:pids){cust_clause}
    GROUP BY si.product_id, si.customer
),
stockout_agg AS (
    SELECT so.product_id, so.customer,
        SUM(CASE WHEN so.order_id IS NULL THEN so.quantity - so.returned_quantity ELSE 0 END) AS direct_stockout_qty,
        SUM(CASE WHEN so.order_id IS NOT NULL AND (o.order_type IS NULL OR o.order_type = 'regular')
            THEN so.quantity - so.returned_quantity ELSE 0 END) AS regular_stockout_qty,
        SUM(CASE WHEN o.order_type = 'custom' THEN so.quantity - so.returned_quantity ELSE 0 END) AS custom_stockout_qty
    FROM stock_out so
    LEFT JOIN "order" o ON so.order_id = o.id
    WHERE so.stockin_id IS NULL AND so.product_id = ANY(:pids){cust_clause}
    GROUP BY so.product_id, so.customer
),
order_agg AS (
    SELECT o.product_id, o.customer,
        SUM(CASE WHEN o.order_type IS NULL OR o.order_type = 'regular' THEN o.quantity ELSE 0 END) AS regular_order_qty,
        SUM(CASE WHEN o.order_type = 'custom' THEN o.quantity ELSE 0 END) AS custom_order_qty,
        1 AS has_order
    FROM "order" o
    WHERE o.product_id = ANY(:pids){cust_clause}
    GROUP BY o.product_id, o.customer
),
country_agg AS (
    SELECT o.product_id, o.customer,
        COALESCE(o.country, '常规') AS country, SUM(o.quantity) AS qty
    FROM "order" o
    WHERE o.product_id = ANY(:pids) AND o.order_type = 'custom'{cust_clause}
    GROUP BY o.product_id, o.customer, COALESCE(o.country, '常规')
),
merged AS (
    SELECT
        COALESCE(si.product_id, so.product_id, od.product_id) AS product_id,
        COALESCE(si.customer, so.customer, od.customer) AS customer,
        COALESCE(si.stockin_qty, 0) AS stockin_qty,
        CASE WHEN si.product_id IS NOT NULL THEN true ELSE false END AS has_stockin,
        COALESCE(so.direct_stockout_qty, 0) AS direct_stockout_qty,
        COALESCE(so.regular_stockout_qty, 0) AS regular_stockout_qty,
        COALESCE(so.custom_stockout_qty, 0) AS custom_stockout_qty,
        COALESCE(od.regular_order_qty, 0) AS regular_order_qty,
        COALESCE(od.custom_order_qty, 0) AS custom_order_qty,
        CASE WHEN od.product_id IS NOT NULL THEN true ELSE false END AS has_order
    FROM stockin_agg si
    FULL OUTER JOIN stockout_agg so ON si.product_id = so.product_id AND si.customer = so.customer
    FULL OUTER JOIN order_agg od
        ON COALESCE(si.product_id, so.product_id) = od.product_id
        AND COALESCE(si.customer, so.customer) = od.customer
),
inventory_calc AS (
    SELECT m.*,
        GREATEST(0, m.regular_order_qty - m.direct_stockout_qty - m.regular_stockout_qty) AS remaining_reg,
        GREATEST(0, m.custom_order_qty - m.custom_stockout_qty) AS remaining_cus,
        m.stockin_qty + GREATEST(0, m.regular_order_qty - m.direct_stockout_qty - m.regular_stockout_qty)
            + GREATEST(0, m.custom_order_qty - m.custom_stockout_qty) AS total_qty
    FROM merged m
),
filtered AS (
    SELECT ic.*, p.name AS product_name, p.barcode AS product_barcode
    FROM inventory_calc ic
    JOIN product p ON p.id = ic.product_id
    WHERE (ic.has_stockin OR ic.has_order) AND ic.total_qty > 0
    {"AND EXISTS (SELECT 1 FROM country_agg ca WHERE ca.product_id = ic.product_id AND ca.customer = ic.customer AND ca.country = :country)" if country else ""}
),
-- 全量统计（不受 LIMIT 影响）
stats_cte AS (
    SELECT COUNT(*) AS total_count,
           COALESCE(SUM(f.stockin_qty), 0) AS sum_stockin,
           COALESCE(SUM(f.remaining_reg + f.remaining_cus), 0) AS sum_order,
           COALESCE(SUM(f.total_qty), 0) AS sum_stock
    FROM filtered f
),
-- 全量国家列表（不受国家筛选影响）
all_countries_cte AS (
    SELECT STRING_AGG(DISTINCT ca.country, '|') AS countries
    FROM country_agg ca WHERE ca.country != '常规'
),
-- 全量客户列表（不受客户筛选影响）
all_customers_cte AS (
    SELECT STRING_AGG(DISTINCT customer, '|') AS customers
    FROM (
        SELECT DISTINCT customer FROM stockin_agg WHERE customer IS NOT NULL
        UNION
        SELECT DISTINCT customer FROM stockout_agg WHERE customer IS NOT NULL
        UNION
        SELECT DISTINCT customer FROM order_agg WHERE customer IS NOT NULL
    ) sub
)
SELECT f.product_id, f.customer, f.product_name, f.product_barcode,
    f.stockin_qty, f.direct_stockout_qty, f.regular_stockout_qty, f.custom_stockout_qty,
    f.regular_order_qty, f.custom_order_qty, f.remaining_reg, f.remaining_cus, f.total_qty,
    (SELECT STRING_AGG(ca.country || ':' || ca.qty::text, '|')
     FROM country_agg ca WHERE ca.product_id = f.product_id AND ca.customer = f.customer) AS country_data,
    ac.countries AS all_countries_str,
    auc.customers AS all_customers_str,
    s.total_count, s.sum_stockin, s.sum_order, s.sum_stock
FROM filtered f
CROSS JOIN all_countries_cte ac
CROSS JOIN all_customers_cte auc
CROSS JOIN stats_cte s
ORDER BY f.customer, f.product_name
LIMIT :limit OFFSET :offset
""")

    params['limit'] = per_page
    params['offset'] = (page - 1) * per_page
    if country:
        params['country'] = country

    result = await db.execute(cte_sql, params)
    rows = result.all()
    if not rows:
        # 即使无匹配数据，仍需获取国家列表
        all_countries = await _get_all_countries(db, pids_param, search_customer)
        all_customers = await _get_all_customers(db, pids_param)
        return _empty_inventory_response(page, per_page, all_countries, all_customers)

    all_countries: list[str] = []
    all_customers: list[str] = []
    total_items = 0
    sum_stockin = 0
    sum_order = 0
    sum_stock = 0
    inventory_data = []

    for row in rows:
        if not all_countries and row.all_countries_str:
            all_countries = sorted(row.all_countries_str.split('|'))
        if not all_customers and row.all_customers_str:
            all_customers = sorted(row.all_customers_str.split('|'))
        total_items = row.total_count
        sum_stockin = int(row.sum_stockin)
        sum_order = int(row.sum_order)
        sum_stock = int(row.sum_stock)

        country_data = _parse_country_data(row.country_data or '')
        so_total = int(row.direct_stockout_qty) + int(row.regular_stockout_qty) + int(row.custom_stockout_qty)
        remaining_reg = int(row.remaining_reg)
        remaining_cus = int(row.remaining_cus)

        inventory_data.append({
            'customer': row.customer,
            'product_name': row.product_name,
            'product_barcode': row.product_barcode or '',
            'order_quantity': remaining_reg if remaining_reg > 0 else '',
            'country_orders': country_data,
            'stockin_quantity': int(row.stockin_qty) if int(row.stockin_qty) > 0 else '',
            'stockout_quantity': so_total if so_total > 0 else '',
            'total_stock': int(row.total_qty) if int(row.total_qty) > 0 else '',
        })

    return {
        'inventory_data': inventory_data,
        'total_order_qty': sum_order,
        'total_stockin_qty': sum_stockin,
        'total_stock': sum_stock,
        'all_countries': all_countries,
        'all_customers': all_customers,
        'total_items': total_items,
        'page': page,
        'per_page': per_page,
    }


def _empty_inventory_response(page: int = 1, per_page: int = 50, all_countries: list | None = None, all_customers: list | None = None) -> dict:
    """构造空库存响应"""
    return {
        'inventory_data': [],
        'total_order_qty': 0,
        'total_stockin_qty': 0,
        'total_stock': 0,
        'all_countries': all_countries or [],
        'all_customers': all_customers or [],
        'total_items': 0,
        'page': page,
        'per_page': per_page,
    }


def _parse_country_data(raw: str) -> dict:
    """解析 country_data 字符串为字典"""
    country_data: dict[str, int] = {}
    if not raw:
        return country_data
    for item in raw.split('|'):
        if ':' in item:
            c, q = item.split(':', 1)
            country_data[c] = int(q)
    return country_data


async def _get_all_countries(db: AsyncSession, pids: tuple, search_customer: str = '') -> list[str]:
    """获取所有定制国家列表（用于空结果时）"""
    cust_clause = " AND customer = :sc" if search_customer else ''
    params: dict = {'pids': pids}
    if search_customer:
        params['sc'] = search_customer
    sql = text(f"""
        SELECT DISTINCT COALESCE(o.country, '常规') AS country
        FROM "order" o
        WHERE o.product_id = ANY(:pids) AND o.order_type = 'custom'{cust_clause}
          AND o.country IS NOT NULL AND o.country != '常规'
    """)
    result = await db.execute(sql, params)
    return sorted(row[0] for row in result.all())

async def _get_all_customers(db: AsyncSession, pids: tuple) -> list[str]:
    """获取所有客户列表（用于空结果时）"""
    sql = text("""
        SELECT DISTINCT customer FROM (
            SELECT DISTINCT customer FROM stock_in WHERE product_id = ANY(:pids) AND customer IS NOT NULL
            UNION
            SELECT DISTINCT customer FROM stock_out WHERE product_id = ANY(:pids) AND customer IS NOT NULL
            UNION
            SELECT DISTINCT customer FROM "order" WHERE product_id = ANY(:pids) AND customer IS NOT NULL
        ) sub
    """)
    result = await db.execute(sql, {'pids': pids})
    return sorted(row[0] for row in result.all())

async def _resolve_products(db: AsyncSession, search: str) -> list[int]:
    if not search:
        result = await db.execute(select(Product.id))
        return [row[0] for row in result.all()]
    escaped = escape_like(search)
    result = await db.execute(select(Product.id).where(or_(Product.name.like(f'%{escaped}%', escape='\\'), Product.barcode.like(f'%{escaped}%', escape='\\'))))
    return [row[0] for row in result.all()]

async def _fetch_inventory(db: AsyncSession, pids: list[int], cust: str='') -> list[dict]:
    params = {'pids': tuple(pids)}
    c = ''
    if cust:
        params['sc'] = cust
        c = ' AND customer = :sc'
    stockin_sql = text('SELECT si.product_id, si.customer, SUM(si.quantity - COALESCE(sub.consumed, 0)) AS stockin_qty, 1 AS has_stockin FROM stock_in si LEFT JOIN (  SELECT stockin_id, SUM(quantity - returned_quantity) AS consumed   FROM stock_out WHERE stockin_id IS NOT NULL AND product_id = ANY(:pids)   GROUP BY stockin_id) sub ON sub.stockin_id = si.id WHERE si.product_id = ANY(:pids)' + c + ' GROUP BY si.product_id, si.customer')
    stockout_sql = text('SELECT so.product_id, so.customer, SUM(CASE WHEN so.order_id IS NULL THEN so.quantity - so.returned_quantity ELSE 0 END) AS direct_stockout_qty, SUM(CASE WHEN so.order_id IS NOT NULL AND (o.order_type IS NULL OR o.order_type = \'regular\') THEN so.quantity - so.returned_quantity ELSE 0 END) AS regular_stockout_qty, SUM(CASE WHEN o.order_type = \'custom\' THEN so.quantity - so.returned_quantity ELSE 0 END) AS custom_stockout_qty FROM stock_out so LEFT JOIN "order" o ON so.order_id = o.id WHERE so.stockin_id IS NULL AND so.product_id = ANY(:pids)' + c + ' GROUP BY so.product_id, so.customer')
    order_sql = text('SELECT o.product_id, o.customer, SUM(CASE WHEN o.order_type IS NULL OR o.order_type = \'regular\' THEN o.quantity ELSE 0 END) AS regular_order_qty, SUM(CASE WHEN o.order_type = \'custom\' THEN o.quantity ELSE 0 END) AS custom_order_qty, 1 AS has_order FROM "order" o WHERE o.product_id = ANY(:pids)' + c + ' GROUP BY o.product_id, o.customer')
    country_sql = text('SELECT o.product_id, o.customer, COALESCE(o.country, \'常规\') AS country, SUM(o.quantity) AS qty FROM "order" o WHERE o.product_id = ANY(:pids) AND o.order_type = \'custom\'' + c + " GROUP BY o.product_id, o.customer, COALESCE(o.country, '常规')")
    si = await _run_sql(db, stockin_sql, params)
    so = await _run_sql(db, stockout_sql, params)
    od = await _run_sql(db, order_sql, params)
    ct = await _run_sql(db, country_sql, params)
    pnames = await _get_prod_names(db, pids)
    merged = {}
    for r in si:
        k = (r['product_id'], r['customer'])
        merged[k] = dict(r)
        for fld in ('direct_stockout_qty', 'regular_stockout_qty', 'custom_stockout_qty', 'regular_order_qty', 'custom_order_qty'):
            merged[k].setdefault(fld, 0)
        merged[k].setdefault('has_order', 0)
        merged[k].setdefault('country_data', '')
    for r in so:
        k = (r['product_id'], r['customer'])
        if k not in merged:
            merged[k] = {'stockin_qty': 0, 'has_stockin': 0, 'regular_order_qty': 0, 'custom_order_qty': 0, 'has_order': 0, 'country_data': ''}
        merged[k]['direct_stockout_qty'] = r['direct_stockout_qty']
        merged[k]['regular_stockout_qty'] = r['regular_stockout_qty']
        merged[k]['custom_stockout_qty'] = r['custom_stockout_qty']
    for r in od:
        k = (r['product_id'], r['customer'])
        if k not in merged:
            merged[k] = {'stockin_qty': 0, 'has_stockin': 0, 'direct_stockout_qty': 0, 'regular_stockout_qty': 0, 'custom_stockout_qty': 0, 'country_data': ''}
        merged[k]['regular_order_qty'] = r['regular_order_qty']
        merged[k]['custom_order_qty'] = r['custom_order_qty']
        merged[k]['has_order'] = r['has_order']
    cdict = {}
    for r in ct:
        k = (r['product_id'], r['customer'])
        e = f"{r['country']}:{r['qty']}"
        cdict[k] = (cdict.get(k, '') + '|' + e).lstrip('|')
    for k in merged:
        merged[k]['country_data'] = cdict.get(k, '')
    result = []
    for k, data in merged.items():
        pid = k[0]
        data['customer'] = k[1]
        data['product_name'] = pnames.get(pid, {}).get('name', '')
        data['product_barcode'] = pnames.get(pid, {}).get('barcode', '')
        result.append(data)
    return result

async def _run_sql(db: AsyncSession, sql, params: dict) -> list[dict]:
    result = await db.execute(sql, params)
    cols = list(result.keys())
    return [dict(zip(cols, row, strict=False)) for row in result.all()]

async def _get_prod_names(db: AsyncSession, pids: list[int]) -> dict:
    result = await db.execute(select(Product.id, Product.name, Product.barcode).where(Product.id.in_(pids)))
    return {row[0]: {'name': row[1], 'barcode': row[2] or ''} for row in result.all()}

def _parse_date_preserve_time(date_str: str, old_time: datetime | None=None) -> datetime:
    """解析入库日期（保留原始时间部分）"""
    try:
        base = datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        raise ValueError('日期格式不正确！') from None
    now = datetime.now(UTC)
    if old_time and (old_time.hour != 0 or old_time.minute != 0 or old_time.second != 0):
        return datetime(base.year, base.month, base.day, old_time.hour, old_time.minute, old_time.second)
    else:
        return datetime(base.year, base.month, base.day, now.hour, now.minute, now.second)

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
        try:
            for orig_idx, item in validated:
                product_id = item.get('product_id')
                customer = str(item.get('customer', '')).strip()
                quantity = int(item.get('quantity', 0))
                note = item.get('note', '')
                order_type = item.get('order_type', 'regular') or 'regular'
                country = item.get('country') or None
                stockin_date_str = item.get('stockin_date') or ''
                stockin_date = _parse_date_preserve_time(stockin_date_str) if stockin_date_str else datetime.now(UTC).replace(tzinfo=None)
                try:
                    async with db.begin_nested():
                        stockin = await create_stockin_core(db, product_id, quantity, customer, stockin_date, note, order_type, country)
                    results[orig_idx] = {'success': True, 'stockin_no': stockin.stockin_no, 'id': stockin.id}
                except ValueError as e:
                    results[orig_idx] = {'success': False, 'error': str(e), 'id': item.get('id', '未知')}
                except (TypeError, OSError) as e:
                    logger.error(f'批量入库单项失败: {e}', exc_info=True)
                    results[orig_idx] = {'success': False, 'error': str(e) or '入库处理失败，请稍后重试', 'id': item.get('id', '未知')}
            await db.commit()
        except (SQLAlchemyError, ValueError, TypeError, OSError):
            await db.rollback()
            raise
    return {'success': True, 'results': results}

async def batch_create_stockouts(db: AsyncSession, stockouts_data: list) -> dict:
    """批量创建出库记录"""
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
    results = [None] * len(stockouts_data)
    for idx, err in errors_map.items():
        results[idx] = {'success': False, 'error': err, 'id': stockouts_data[idx].get('id', '未知')}
    if validated:
        try:
            for orig_idx, item in validated:
                product_id = item.get('product_id')
                customer = str(item.get('customer', '')).strip()
                quantity = int(item.get('quantity', 0))
                order_type = item.get('order_type', 'regular') or 'regular'
                country = item.get('country', '') or None
                note = item.get('note', '')
                try:
                    async with db.begin_nested():
                        created = await create_stockout_core(db, product_id, quantity, customer, datetime.now(UTC).replace(tzinfo=None), note, order_type, country)
                    stockout_nos = [s.stockout_no for s in created] if created else []
                    results[orig_idx] = {'success': True, 'stockout_no': stockout_nos[0] if stockout_nos else '', 'id': item.get('id', '未知')}
                except ValueError as e:
                    results[orig_idx] = {'success': False, 'error': str(e), 'id': item.get('id', '未知')}
                except (TypeError, OSError) as e:
                    logger.error(f'批量出库单项失败: {e}', exc_info=True)
                    results[orig_idx] = {'success': False, 'error': str(e) or '出库处理失败，请稍后重试', 'id': item.get('id', '未知')}
            await db.commit()
        except (SQLAlchemyError, ValueError, TypeError, OSError):
            await db.rollback()
            raise
    return {'success': True, 'results': results}
