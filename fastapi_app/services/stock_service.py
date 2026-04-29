"""
库存管理业务逻辑服务

核心 CRUD 和库存计算已统一至 fastapi_app.shared.stock_crud_service。
本服务负责异步适配层：将同步 shared 函数包装为异步调用，
并处理事件发布等 FastAPI 特有逻辑。
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, joinedload
from sqlalchemy.exc import SQLAlchemyError

from fastapi_app.shared_models import (
    InventoryLog, Order, Product, StockIn, StockOut
)
from fastapi_app.shared.stock_concurrency import get_product_for_update
from fastapi_app.services import escape_like
from fastapi_app.services.batch_service import (
    calculate_available_shipment_quantity,
    generate_stockin_number,
    generate_stockout_number,
)
from fastapi_app.services.notification_service import publish_stock_event, StockEvent
from fastapi_app.core.cache import invalidate_cache

logger = logging.getLogger(__name__)


async def _create_stockin_record(
    db: AsyncSession,
    product_id: int,
    quantity: int,
    customer: str,
    stockin_date: datetime,
    note: str,
) -> StockIn:
    if quantity <= 0:
        raise ValueError('入库数量必须大于0')

    stockin = StockIn(
        stockin_no=await generate_stockin_number(db),
        product_id=product_id,
        quantity=quantity,
        customer=customer,
        stockin_date=stockin_date,
        note=note,
    )
    db.add(stockin)
    await db.flush()

    product = await get_product_for_update(db, product_id)
    product.current_stock += quantity

    db.add(InventoryLog(
        product_id=product_id,
        change_type='入库',
        change_quantity=quantity,
        related_id=str(stockin.id),
        note=f'入库ID：{stockin.id}',
    ))
    await db.flush()
    return stockin


async def _update_stockin_record(
    db: AsyncSession,
    stockin: StockIn,
    quantity: int,
    customer: str,
    stockin_date: datetime,
    note: str,
) -> StockIn:
    old_quantity = stockin.quantity
    stockin.quantity = quantity
    stockin.customer = customer
    stockin.stockin_date = stockin_date
    stockin.note = note

    if quantity != old_quantity:
        product = await get_product_for_update(db, stockin.product_id)
        product.current_stock += quantity - old_quantity
        db.add(InventoryLog(
            product_id=stockin.product_id,
            change_type='入库修改',
            change_quantity=quantity - old_quantity,
            related_id=str(stockin.id),
            note=f'入库修改ID：{stockin.id}',
        ))
    await db.flush()
    return stockin


async def _delete_stockin_record(db: AsyncSession, stockin: StockIn) -> None:
    if stockin.stockin_stockouts:
        raise ValueError('该入库记录已有出库关联，无法删除')

    product = await get_product_for_update(db, stockin.product_id)
    product.current_stock -= stockin.quantity
    if product.current_stock < 0:
        logger.warning(f'库存出现负数：产品{product.name}(ID:{product.id})，当前库存{product.current_stock}')

    db.add(InventoryLog(
        product_id=stockin.product_id,
        change_type='入库删除',
        change_quantity=-stockin.quantity,
        related_id=str(stockin.id),
        note=f'入库删除ID：{stockin.id}',
    ))
    await db.delete(stockin)
    await db.flush()


async def _create_stockout_records(
    db: AsyncSession,
    product_id: int,
    quantity: int,
    customer: str,
    stockout_date: datetime,
    note: str,
    order_type: str = 'regular',
    country: str | None = None,
) -> list[StockOut]:
    product = await get_product_for_update(db, product_id)

    if product.current_stock < quantity:
        raise ValueError('库存不足！')

    if order_type == 'custom' and not country:
        raise ValueError('定制订单必须填写国家名称！')

    shipment_info = await calculate_available_shipment_quantity(
        db, product_id, customer, order_type=order_type, country=country
    )
    if shipment_info['available_quantity'] <= 0:
        raise ValueError('该客户没有可用的订单支持出货！请先创建订单。')
    if quantity > shipment_info['available_quantity']:
        raise ValueError(
            f'出货数量超过可出货量！订单总量：{shipment_info["order_quantity"]}，'
            f'已出货：{shipment_info["shipped_quantity"]}，'
            f'可出货：{shipment_info["available_quantity"]}'
        )

    remaining_qty = quantity
    created_stockouts: list[StockOut] = []
    for order_detail in shipment_info['orders']:
        if remaining_qty <= 0:
            break
        if order_detail['available'] <= 0:
            continue

        ship_qty = min(remaining_qty, order_detail['available'])
        stockout = StockOut(
            stockout_no=await generate_stockout_number(db),
            product_id=product_id,
            quantity=ship_qty,
            stockout_date=stockout_date,
            customer=customer,
            order_id=order_detail['order_id'],
            note=note,
        )
        db.add(stockout)
        await db.flush()
        created_stockouts.append(stockout)
        remaining_qty -= ship_qty

    product.current_stock -= quantity
    db.add(InventoryLog(
        product_id=product_id,
        change_type='出库',
        change_quantity=-quantity,
        related_id=','.join(str(s.id) for s in created_stockouts) if created_stockouts else '',
        note=f'出库数量：{quantity}',
    ))
    await db.flush()
    return created_stockouts


async def _update_stockout_record(
    db: AsyncSession,
    stockout: StockOut,
    new_quantity: int,
    customer: str,
    stockout_date: datetime,
    note: str,
) -> StockOut:
    if stockout.stockin_id is not None:
        raise ValueError('订单抵扣的出货记录不能直接编辑！请通过订单管理进行修改。')

    old_quantity = stockout.quantity
    product = await get_product_for_update(db, stockout.product_id)

    if product.current_stock + old_quantity < new_quantity:
        raise ValueError('库存不足！')

    if customer:
        shipment_info = await calculate_available_shipment_quantity(db, stockout.product_id, customer)
        available_with_current = shipment_info['available_quantity'] + old_quantity
        if new_quantity > available_with_current:
            raise ValueError(
                f'出货数量超过可出货量！订单总量：{shipment_info["order_quantity"]}，'
                f'可出货（含当前记录）：{available_with_current}'
            )

    stockout.quantity = new_quantity
    stockout.stockout_date = stockout_date
    stockout.customer = customer
    stockout.note = note

    if new_quantity != old_quantity:
        product.current_stock -= (new_quantity - old_quantity)
        db.add(InventoryLog(
            product_id=stockout.product_id,
            change_type='出库修改',
            change_quantity=-(new_quantity - old_quantity),
            related_id=str(stockout.id),
            note=f'出库修改ID：{stockout.id}',
        ))
    await db.flush()
    return stockout


async def _delete_stockout_record(db: AsyncSession, stockout: StockOut) -> None:
    if stockout.stockin_id is not None:
        raise ValueError('订单抵扣的出货记录不能直接删除！请通过订单管理进行修改。')

    product = await get_product_for_update(db, stockout.product_id)
    product.current_stock += stockout.quantity
    db.add(InventoryLog(
        product_id=stockout.product_id,
        change_type='出库删除',
        change_quantity=stockout.quantity,
        related_id=str(stockout.id),
        note=f'出库删除ID：{stockout.id}',
    ))
    await db.delete(stockout)
    await db.flush()


# ==================== 入库管理 ====================

async def get_stockins(db: AsyncSession, page: int = 1, per_page: int = 50) -> dict:
    """获取入库列表（含关联数据，支持分页）"""
    total = (await db.execute(select(func.count(StockIn.id)))).scalar() or 0
    result = await db.execute(
        select(StockIn)
        .options(
            joinedload(StockIn.product),
            selectinload(StockIn.stockin_stockouts)
        )
        .order_by(StockIn.stockin_date.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    stockins = result.scalars().unique().all()

    data = []
    for s in stockins:
        deducted = sum(so.quantity for so in s.stockin_stockouts) if s.stockin_stockouts else 0
        data.append({
            'id': s.id,
            'stockin_no': s.stockin_no,
            'stockin_date': s.stockin_date.strftime('%Y-%m-%d') if s.stockin_date else '',
            'customer': s.customer,
            'product': {
                'id': s.product.id,
                'name': s.product.name,
                'barcode': s.product.barcode or '',
                'image': s.product.image or ''
            } if s.product else None,
            'quantity': s.quantity,
            'deducted': deducted,
            'note': s.note or '',
        })
    return {'items': data, 'total': total, 'page': page, 'per_page': per_page}


async def create_stockin(db: AsyncSession, product_id: int, quantity: int,
                         customer: str, stockin_date_str: str,
                         note: str) -> dict:
    """创建入库记录"""
    stockin_date = _parse_date_preserve_time(stockin_date_str)

    try:
        stockin = await _create_stockin_record(db, product_id, quantity, customer, stockin_date, note)
        await db.commit()
    except (SQLAlchemyError, ValueError):
        await db.rollback()
        raise

    # 失效相关缓存
    await invalidate_cache("inventory:*")
    await invalidate_cache("orders:*")

    # 发布库存变更事件（数据已提交，事件丢失不影响一致性）
    try:
        product = await db.get(Product, product_id)
        if product is None:
            logger.warning(f'入库事件发布失败：产品ID {product_id} 不存在')
        else:
            await publish_stock_event(StockEvent.STOCK_CHANGED, {
                'product_id': product_id, 'product_name': product.name,
                'change_type': '入库', 'quantity': quantity,
                'current_stock': product.current_stock,
            })
    except (OSError, ConnectionError, ValueError) as e:
        logger.warning(f'入库事件发布失败（不影响数据）: {e}')
    logger.info(f'入库添加成功：{stockin.stockin_no}，客户：{customer}，产品ID：{product_id}，数量：{quantity}')

    return {'id': stockin.id, 'stockin_no': stockin.stockin_no}


async def update_stockin(db: AsyncSession, stockin_id: int, quantity: int,
                         customer: str, stockin_date_str: str,
                         note: str) -> None:
    """更新入库记录"""
    result = await db.execute(
        select(StockIn)
        .where(StockIn.id == stockin_id)
        .options(selectinload(StockIn.stockin_stockouts))
        .with_for_update()
    )
    stockin_obj = result.scalar_one_or_none()
    if not stockin_obj:
        raise ValueError('入库记录不存在')
    stockin_date = _parse_date_preserve_time(stockin_date_str, stockin_obj.stockin_date)
    old_quantity = stockin_obj.quantity
    old_stockin_no = stockin_obj.stockin_no

    try:
        await _update_stockin_record(db, stockin_obj, quantity, customer, stockin_date, note)
        await db.commit()
    except (SQLAlchemyError, ValueError):
        await db.rollback()
        raise

    await invalidate_cache("inventory:*")
    await invalidate_cache("orders:*")
    logger.info(f'入库编辑成功：{old_stockin_no}，数量变更：{old_quantity} -> {quantity}')


async def delete_stockin(db: AsyncSession, stockin_id: int) -> None:
    """删除入库记录"""
    result = await db.execute(
        select(StockIn)
        .where(StockIn.id == stockin_id)
        .options(selectinload(StockIn.stockin_stockouts))
    )
    stockin_obj = result.scalar_one_or_none()
    if not stockin_obj:
        raise ValueError('入库记录不存在')
    stockin_no = stockin_obj.stockin_no

    try:
        await _delete_stockin_record(db, stockin_obj)
        await db.commit()
    except (SQLAlchemyError, ValueError):
        await db.rollback()
        raise

    await invalidate_cache("inventory:*")
    await invalidate_cache("orders:*")
    logger.info(f'入库删除成功：{stockin_no}，数量：{stockin_obj.quantity}')


# ==================== 出库管理 ====================

async def get_stockouts(db: AsyncSession, page: int = 1, per_page: int = 50) -> dict:
    """获取出库列表（仅独立出库，非抵扣，支持分页）"""
    base_condition = StockOut.stockin_id.is_(None)
    base_query = select(StockOut).where(base_condition)
    total = (await db.execute(select(func.count(StockOut.id)).where(base_condition))).scalar() or 0
    result = await db.execute(
        base_query
        .options(joinedload(StockOut.product), joinedload(StockOut.order))
        .order_by(StockOut.stockout_date.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    stockouts = result.scalars().unique().all()

    data = []
    for s in stockouts:
        data.append({
            'id': s.id,
            'stockout_no': s.stockout_no,
            'stockout_date': s.stockout_date.strftime('%Y-%m-%d') if s.stockout_date else '',
            'customer': s.customer,
            'product': {
                'id': s.product.id,
                'name': s.product.name,
                'barcode': s.product.barcode or '',
                'image': s.product.image or ''
            } if s.product else None,
            'quantity': s.quantity,
            'note': s.note or '',
            'order_type': s.order.order_type if s.order else 'regular',
            'country': s.order.country if s.order and s.order.country else '',
        })
    return {'items': data, 'total': total, 'page': page, 'per_page': per_page}


async def create_stockout(db: AsyncSession, product_id: int, quantity: int,
                          customer: str, stockout_date_str: str,
                          note: str, order_type: str = 'regular',
                          country: str | None = None) -> dict:
    """创建出库记录"""
    stockout_date = _parse_date_preserve_time(stockout_date_str)

    try:
        created = await _create_stockout_records(
            db, product_id, quantity, customer, stockout_date, note, order_type, country
        )
        await db.commit()
    except (SQLAlchemyError, ValueError):
        await db.rollback()
        raise

    # 失效相关缓存
    await invalidate_cache("inventory:*")
    await invalidate_cache("orders:*")

    # 发布库存变更事件（数据已提交，事件丢失不影响一致性）
    try:
        product = await db.get(Product, product_id)
        if product is not None:
            await publish_stock_event(StockEvent.STOCK_CHANGED, {
                'product_id': product_id, 'product_name': product.name,
                'change_type': '出库', 'quantity': quantity,
                'current_stock': product.current_stock,
            })
    except (OSError, ConnectionError, ValueError) as e:
        logger.warning(f'出库事件发布失败（不影响数据）: {e}')
    logger.info(f'出库添加成功：产品ID：{product_id}，数量：{quantity}，客户：{customer}')

    return {'quantity': quantity}


async def update_stockout(db: AsyncSession, stockout_id: int, new_quantity: int,
                          customer: str, stockout_date_str: str,
                          note: str) -> None:
    """更新出库记录"""
    result = await db.execute(
        select(StockOut).where(StockOut.id == stockout_id).with_for_update()
    )
    stockout_obj = result.scalar_one_or_none()
    if not stockout_obj:
        raise ValueError('出库记录不存在')

    stockout_date = _parse_date_preserve_time(stockout_date_str)
    old_quantity = stockout_obj.quantity
    old_stockout_no = stockout_obj.stockout_no

    try:
        await _update_stockout_record(db, stockout_obj, new_quantity, customer, stockout_date, note)
        await db.commit()
    except (SQLAlchemyError, ValueError):
        await db.rollback()
        raise

    await invalidate_cache("inventory:*")
    await invalidate_cache("orders:*")
    logger.info(f'出库编辑成功：{old_stockout_no}，数量变更：{old_quantity} -> {new_quantity}')


async def delete_stockout(db: AsyncSession, stockout_id: int) -> None:
    """删除出库记录"""
    result = await db.execute(
        select(StockOut).where(StockOut.id == stockout_id).with_for_update()
    )
    stockout_obj = result.scalar_one_or_none()
    if not stockout_obj:
        raise ValueError('出库记录不存在')
    stockout_no = stockout_obj.stockout_no

    try:
        await _delete_stockout_record(db, stockout_obj)
        await db.commit()
    except (SQLAlchemyError, ValueError):
        await db.rollback()
        raise

    await invalidate_cache("inventory:*")
    await invalidate_cache("orders:*")
    logger.info(f'出库删除成功：{stockout_no}，数量：{stockout_obj.quantity}')


# ==================== 库存查看 ====================

async def get_inventory(db: AsyncSession, search_customer: str = '',
                        search_product: str = '') -> dict:
    """
    获取库存数据（按产品+客户维度汇总）
    """
    products_query = (
        select(Product)
        .options(
            selectinload(Product.orders),
            selectinload(Product.stockins).selectinload(StockIn.stockin_stockouts),
        )
    )

    if search_product:
        escaped = escape_like(search_product)
        products_query = products_query.where(
            or_(
                Product.name.like(f'%{escaped}%', escape='\\'),
                Product.barcode.like(f'%{escaped}%', escape='\\'),
            )
        )

    product_result = await db.execute(products_query)
    products = product_result.scalars().unique().all()

    if not products:
        return {
            'inventory_data': [],
            'total_order_qty': 0,
            'total_stockin_qty': 0,
            'total_stock': 0,
            'all_countries': [],
        }

    product_ids = [p.id for p in products]
    stockout_result = await db.execute(
        select(StockOut).where(
            StockOut.product_id.in_(product_ids),
            StockOut.stockin_id.is_(None),
        )
    )
    all_stockouts = stockout_result.scalars().all()

    stockout_map = {}
    for so in all_stockouts:
        key = (so.product_id, so.customer or '')
        if key not in stockout_map:
            stockout_map[key] = {'direct': 0, 'order': 0, 'total': 0}
        stockout_map[key]['total'] += so.quantity
        if so.order_id:
            stockout_map[key]['order'] += so.quantity
        else:
            stockout_map[key]['direct'] += so.quantity

    inventory_data = []
    total_order_qty = 0
    total_stockin_qty = 0
    total_stock = 0

    for product in products:
        stockins = product.stockins
        if search_customer:
            stockins = [s for s in stockins if s.customer == search_customer]

        product_customers = set()
        for stockin in stockins:
            if stockin.customer:
                product_customers.add(stockin.customer)

        product_stockouts = [so for so in all_stockouts if so.product_id == product.id]
        if search_customer:
            product_stockouts = [so for so in product_stockouts if so.customer == search_customer]
        for stockout in product_stockouts:
            if stockout.customer:
                product_customers.add(stockout.customer)

        orders = product.orders
        if search_customer:
            orders = [order for order in orders if order.customer == search_customer]
        product_customers.update(order.customer for order in orders)

        for customer in product_customers:
            cust_stockin_qty = sum(
                stockin.quantity - sum(so.quantity for so in stockin.stockin_stockouts)
                for stockin in product.stockins if stockin.customer == customer
            )

            so_key = (product.id, customer)
            so_data = stockout_map.get(so_key, {'direct': 0, 'order': 0, 'total': 0})
            cust_stockout_qty = so_data['total']

            customer_orders = [order for order in orders if order.customer == customer]
            cust_order_total = sum(order.quantity for order in customer_orders)

            country_orders = {}
            for order in customer_orders:
                label = order.country if getattr(order, 'order_type', 'regular') == 'custom' and order.country else '常规'
                country_orders[label] = country_orders.get(label, 0) + order.quantity

            regular_order_qty = country_orders.get('常规', 0)
            custom_order_qty = sum(value for key, value in country_orders.items() if key != '常规')
            total_shipped = so_data['direct'] + so_data['order']
            available_order_qty = max(0, cust_order_total - total_shipped)
            total_qty = cust_stockin_qty + regular_order_qty + custom_order_qty

            has_stockin_record = any(stockin.customer == customer for stockin in product.stockins)
            has_order_record = len(customer_orders) > 0
            has_positive_stock = available_order_qty > 0 or cust_stockin_qty > 0 or total_qty > 0

            if (has_stockin_record or has_order_record) and has_positive_stock:
                inventory_data.append({
                    'customer': customer,
                    'product_name': product.name,
                    'product_barcode': product.barcode or '',
                    'order_quantity': regular_order_qty if regular_order_qty > 0 else '',
                    'country_orders': country_orders,
                    'stockin_quantity': cust_stockin_qty if cust_stockin_qty > 0 else '',
                    'stockout_quantity': cust_stockout_qty if cust_stockout_qty > 0 else '',
                    'total_stock': total_qty if total_qty > 0 else '',
                })
                total_stockin_qty += cust_stockin_qty
                total_order_qty += regular_order_qty + custom_order_qty
                total_stock += total_qty

    all_countries = set()
    for item in inventory_data:
        for key, value in item.get('country_orders', {}).items():
            if key != '常规' and value:
                all_countries.add(key)

    return {
        'inventory_data': inventory_data,
        'total_order_qty': total_order_qty,
        'total_stockin_qty': total_stockin_qty,
        'total_stock': total_stock,
        'all_countries': sorted(all_countries),
    }


# ==================== 内部辅助 ====================

def _parse_date_preserve_time(date_str: str, old_time: datetime | None = None) -> datetime:
    """解析入库日期（保留原始时间部分）"""
    try:
        base = datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        raise ValueError('日期格式不正确！')

    now = datetime.now(timezone.utc)
    if old_time and (old_time.hour != 0 or old_time.minute != 0 or old_time.second != 0):
        return datetime(base.year, base.month, base.day,
                        old_time.hour, old_time.minute, old_time.second)
    else:
        return datetime(base.year, base.month, base.day,
                        now.hour, now.minute, now.second)


async def batch_create_stockins(db: AsyncSession, stockins_data: list) -> dict:
    """批量创建入库记录"""

    # 前置校验（与 batch_create_stockouts 统一使用 errors_map + indexed results 模式）
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
                try:
                    async with db.begin_nested():
                        stockin = await _create_stockin_record(
                            db, product_id, quantity, customer, datetime.now(timezone.utc).replace(tzinfo=None), note
                        )
                    results[orig_idx] = {
                        'success': True,
                        'stockin_no': stockin.stockin_no,
                        'id': stockin.id,
                    }
                except ValueError as e:
                    results[orig_idx] = {'success': False, 'error': str(e), 'id': item.get('id', '未知')}
                except (ValueError, TypeError, OSError) as e:
                    logger.error(f"批量入库单项失败: {e}", exc_info=True)
                    results[orig_idx] = {'success': False, 'error': str(e) or '入库处理失败，请稍后重试', 'id': item.get('id', '未知')}

            await db.commit()
        except (SQLAlchemyError, ValueError, TypeError, OSError):
            await db.rollback()
            raise

    return {'success': True, 'results': results}


async def batch_create_stockouts(db: AsyncSession, stockouts_data: list) -> dict:
    """批量创建出库记录"""

    # 前置校验
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
        if order_type == 'custom' and not country:
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
                        created = await _create_stockout_records(
                            db, product_id, quantity, customer, datetime.now(timezone.utc).replace(tzinfo=None), note, order_type, country
                        )
                    stockout_nos = [s.stockout_no for s in created] if created else []
                    results[orig_idx] = {'success': True, 'stockout_no': stockout_nos[0] if stockout_nos else '', 'id': item.get('id', '未知')}
                except ValueError as e:
                    results[orig_idx] = {'success': False, 'error': str(e), 'id': item.get('id', '未知')}
                except (ValueError, TypeError, OSError) as e:
                    # begin_nested 已自动回滚 savepoint，session 恢复有效状态
                    logger.error(f"批量出库单项失败: {e}", exc_info=True)
                    results[orig_idx] = {'success': False, 'error': str(e) or '出库处理失败，请稍后重试', 'id': item.get('id', '未知')}

            await db.commit()
        except (SQLAlchemyError, ValueError, TypeError, OSError):
            await db.rollback()
            raise

    return {'success': True, 'results': results}
