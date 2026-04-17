"""
库存管理业务逻辑服务

从 Flask stock.py 提取的核心业务逻辑，适配异步 SQLAlchemy。
"""
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select, func, delete, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, joinedload
from sqlalchemy.exc import SQLAlchemyError

from fastapi_app.shared_models import (
    Product, StockIn, StockOut, InventoryLog, Order, Customer
)
from fastapi_app.services.stock_concurrency import get_product_for_update
from fastapi_app.services.notification_service import publish_stock_event, StockEvent
from fastapi_app.services import escape_like

logger = logging.getLogger(__name__)


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
    product = await get_product_for_update(db, product_id)

    stockin_date = _parse_stockin_date(stockin_date_str)

    from fastapi_app.services.batch_service import generate_stockin_number
    stockin_no = await generate_stockin_number(db)

    stockin = StockIn(
        stockin_no=stockin_no,
        product_id=product_id,
        quantity=quantity,
        customer=customer,
        stockin_date=stockin_date,
        note=note
    )
    db.add(stockin)
    await db.flush()

    product.current_stock += quantity

    log = InventoryLog(
        product_id=product_id,
        change_type='入库',
        change_quantity=quantity,
        related_id=str(stockin.id),
        note=f'入库ID：{stockin.id}'
    )
    db.add(log)

    await db.commit()
    await db.refresh(stockin)
    logger.info(f'入库添加成功：{stockin_no}，客户：{customer}，产品：{product.name}，数量：{quantity}')

    # 发布库存变更事件
    publish_stock_event(StockEvent.STOCK_CHANGED, {
        'product_id': product_id, 'product_name': product.name,
        'change_type': '入库', 'quantity': quantity,
        'current_stock': product.current_stock,
    })

    return {'id': stockin.id, 'stockin_no': stockin_no}


async def update_stockin(db: AsyncSession, stockin_id: int, quantity: int,
                         customer: str, stockin_date_str: str,
                         note: str) -> None:
    """更新入库记录"""
    stockin = await db.get(StockIn, stockin_id)
    if not stockin:
        raise ValueError('入库记录不存在')

    stockin_date = _parse_stockin_date(stockin_date_str, stockin.stockin_date)

    old_quantity = stockin.quantity
    stockin.quantity = quantity
    stockin.customer = customer
    stockin.note = note
    stockin.stockin_date = stockin_date

    if quantity != old_quantity:
        product = await get_product_for_update(db, stockin.product_id)
        product.current_stock += (quantity - old_quantity)
        log = InventoryLog(
            product_id=stockin.product_id,
            change_type='入库修改',
            change_quantity=quantity - old_quantity,
            related_id=str(stockin.id),
            note=f'入库修改ID：{stockin.id}'
        )
        db.add(log)

    await db.commit()
    logger.info(f'入库编辑成功：{stockin.stockin_no}，数量变更：{old_quantity} -> {quantity}')


async def delete_stockin(db: AsyncSession, stockin_id: int) -> None:
    """删除入库记录"""
    stockin = await db.get(StockIn, stockin_id)
    if not stockin:
        raise ValueError('入库记录不存在')

    # 检查关联出货
    if stockin.stockin_stockouts:
        raise ValueError('该入库记录已有出库关联，无法删除！')

    product = await get_product_for_update(db, stockin.product_id)
    product.current_stock -= stockin.quantity

    log = InventoryLog(
        product_id=stockin.product_id,
        change_type='入库删除',
        change_quantity=-stockin.quantity,
        related_id=str(stockin.id),
        note=f'入库删除ID：{stockin.id}'
    )
    db.add(log)

    await db.delete(stockin)
    await db.commit()
    logger.info(f'入库删除成功：{stockin.stockin_no}，数量：{stockin.quantity}')


# ==================== 出库管理 ====================

async def get_stockouts(db: AsyncSession, page: int = 1, per_page: int = 50) -> dict:
    """获取出库列表（仅独立出库，非抵扣，支持分页）"""
    base_condition = StockOut.stockin_id.is_(None)
    base_query = select(StockOut).where(base_condition)
    total = (await db.execute(select(func.count(StockOut.id)).where(base_condition))).scalar() or 0
    result = await db.execute(
        base_query
        .options(joinedload(StockOut.product))
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
        })
    return {'items': data, 'total': total, 'page': page, 'per_page': per_page}


async def create_stockout(db: AsyncSession, product_id: int, quantity: int,
                          customer: str, stockout_date_str: str,
                          note: str) -> dict:
    """创建出库记录"""
    product = await get_product_for_update(db, product_id)

    if product.current_stock < quantity:
        raise ValueError('库存不足！')

    stockout_date = datetime.strptime(stockout_date_str, '%Y-%m-%d')

    from fastapi_app.services.batch_service import calculate_available_shipment_quantity
    shipment_info = await calculate_available_shipment_quantity(db, product_id, customer)
    if shipment_info['available_quantity'] <= 0:
        raise ValueError('该客户没有可用的订单支持出货！请先创建订单。')

    if quantity > shipment_info['available_quantity']:
        raise ValueError(
            f'出货数量超过可出货量！订单总量：{shipment_info["order_quantity"]}，'
            f'已出货：{shipment_info["shipped_quantity"]}，'
            f'可出货：{shipment_info["available_quantity"]}'
        )

    from fastapi_app.services.batch_service import generate_stockout_number
    remaining_qty = quantity
    for order_detail in shipment_info['orders']:
        if remaining_qty <= 0:
            break
        if order_detail['available'] > 0:
            ship_qty = min(remaining_qty, order_detail['available'])
            stockout_no = await generate_stockout_number(db)
            stockout = StockOut(
                stockout_no=stockout_no,
                product_id=product_id,
                quantity=ship_qty,
                stockout_date=stockout_date,
                customer=customer,
                order_id=order_detail['order_id'],
                note=note
            )
            db.add(stockout)
            remaining_qty -= ship_qty

    product.current_stock -= quantity

    log = InventoryLog(
        product_id=product_id,
        change_type='出库',
        change_quantity=-quantity,
        related_id='',
        note=f'出库数量：{quantity}'
    )
    db.add(log)

    await db.commit()
    logger.info(f'出库添加成功：产品{product.name}，数量：{quantity}，客户：{customer}')

    # 发布库存变更事件
    publish_stock_event(StockEvent.STOCK_CHANGED, {
        'product_id': product_id, 'product_name': product.name,
        'change_type': '出库', 'quantity': quantity,
        'current_stock': product.current_stock,
    })

    return {'quantity': quantity}


async def update_stockout(db: AsyncSession, stockout_id: int, new_quantity: int,
                          customer: str, stockout_date_str: str,
                          note: str) -> None:
    """更新出库记录"""
    stockout = await db.get(StockOut, stockout_id)
    if not stockout:
        raise ValueError('出库记录不存在')

    if stockout.stockin_id is not None:
        raise ValueError('订单抵扣的出货记录不能直接编辑！请通过订单管理进行修改。')

    stockout_date = datetime.strptime(stockout_date_str, '%Y-%m-%d')

    old_quantity = stockout.quantity

    product = await get_product_for_update(db, stockout.product_id)

    if product.current_stock + old_quantity < new_quantity:
        raise ValueError('库存不足！')

    if customer:
        from fastapi_app.services.batch_service import calculate_available_shipment_quantity
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
        log = InventoryLog(
            product_id=stockout.product_id,
            change_type='出库修改',
            change_quantity=-(new_quantity - old_quantity),
            related_id=str(stockout.id),
            note=f'出库修改ID：{stockout.id}'
        )
        db.add(log)

    await db.commit()
    logger.info(f'出库编辑成功：{stockout.stockout_no}，数量变更：{old_quantity} -> {new_quantity}')


async def delete_stockout(db: AsyncSession, stockout_id: int) -> None:
    """删除出库记录"""
    stockout = await db.get(StockOut, stockout_id)
    if not stockout:
        raise ValueError('出库记录不存在')

    if stockout.stockin_id is not None:
        raise ValueError('订单抵扣的出货记录不能直接删除！请通过订单管理进行修改。')

    product = await get_product_for_update(db, stockout.product_id)
    product.current_stock += stockout.quantity

    log = InventoryLog(
        product_id=stockout.product_id,
        change_type='出库删除',
        change_quantity=stockout.quantity,
        related_id=str(stockout.id),
        note=f'出库删除ID：{stockout.id}'
    )
    db.add(log)

    await db.delete(stockout)
    await db.commit()
    logger.info(f'出库删除成功：{stockout.stockout_no}，数量：{stockout.quantity}')


# ==================== 库存查看 ====================

async def get_inventory(db: AsyncSession, search_customer: str = '',
                        search_product: str = '') -> dict:
    """
    获取库存数据

    业务规则（与Flask一致）：
    - 按产品+客户维度汇总
    - 备货剩余 = 该客户该产品的入库量 - 已被订单抵扣的量
    - 订单可用 = 该客户该产品的订单总量 - 已出货量（非抵扣）
    - 总库存 = 备货剩余 + 订单可用
    """
    products_query = (
        select(Product)
        .options(
            selectinload(Product.orders),
            selectinload(Product.stockins).selectinload(StockIn.stockin_stockouts)
        )
    )

    if search_product:
        products_query = products_query.where(
            Product.name.like(f'%{escape_like(search_product)}%') | Product.barcode.like(f'%{escape_like(search_product)}%')
        )

    result = await db.execute(products_query)
    products = result.scalars().unique().all()

    if not products:
        return {
            'inventory_data': [],
            'total_order_qty': 0,
            'total_stockin_qty': 0,
            'total_stock': 0,
        }

    product_ids = [p.id for p in products]

    # 批量预加载出库记录
    stockout_result = await db.execute(
        select(StockOut).where(
            StockOut.product_id.in_(product_ids),
            StockOut.stockin_id.is_(None)
        )
    )
    all_stockouts = stockout_result.scalars().all()

    # 按 product_id + customer 分组
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
        for s in stockins:
            if s.customer:
                product_customers.add(s.customer)

        all_stockouts_for_product = [so for so in all_stockouts if so.product_id == product.id]
        if search_customer:
            all_stockouts_for_product = [so for so in all_stockouts_for_product if so.customer == search_customer]
        for so in all_stockouts_for_product:
            if so.customer:
                product_customers.add(so.customer)

        orders = product.orders
        if search_customer:
            orders = [o for o in orders if o.customer == search_customer]
        order_customers = set(o.customer for o in orders)
        product_customers.update(order_customers)

        for customer in product_customers:
            cust_stockin_qty = sum(
                s.quantity - sum(so.quantity for so in s.stockin_stockouts)
                for s in product.stockins if s.customer == customer
            )

            so_key = (product.id, customer)
            so_data = stockout_map.get(so_key, {'direct': 0, 'order': 0, 'total': 0})
            cust_stockout_qty = so_data['total']

            customer_orders = [o for o in orders if o.customer == customer]
            cust_order_total = sum(o.quantity for o in customer_orders)

            direct_shipped = so_data['direct']
            order_shipped = so_data['order']
            total_shipped = direct_shipped + order_shipped
            available_order_qty = max(0, cust_order_total - total_shipped)
            total_qty = max(0, cust_stockin_qty + available_order_qty)

            has_stockin_record = any(s.customer == customer for s in product.stockins)
            has_order_record = len(customer_orders) > 0
            has_positive_stock = (available_order_qty > 0 or
                                   cust_stockin_qty > 0 or
                                   total_qty > 0)

            if (has_stockin_record or has_order_record) and has_positive_stock:
                inventory_data.append({
                    'customer': customer,
                    'product_name': product.name,
                    'product_barcode': product.barcode or '',
                    'order_quantity': available_order_qty if available_order_qty > 0 else '',
                    'stockin_quantity': cust_stockin_qty if cust_stockin_qty > 0 else '',
                    'stockout_quantity': cust_stockout_qty if cust_stockout_qty > 0 else '',
                    'total_stock': total_qty if total_qty > 0 else '',
                })
                total_stockin_qty += cust_stockin_qty
                total_order_qty += available_order_qty
                total_stock += total_qty

    return {
        'inventory_data': inventory_data,
        'total_order_qty': total_order_qty,
        'total_stockin_qty': total_stockin_qty,
        'total_stock': total_stock,
    }


# ==================== 内部辅助 ====================

def _parse_stockin_date(date_str: str, old_time: datetime | None = None) -> datetime:
    """解析入库日期（保留原始时间部分）"""
    try:
        base = datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        raise ValueError('日期格式不正确！')

    now = datetime.now()
    if old_time and (old_time.hour != 0 or old_time.minute != 0 or old_time.second != 0):
        return datetime(base.year, base.month, base.day,
                        old_time.hour, old_time.minute, old_time.second)
    else:
        return datetime(base.year, base.month, base.day,
                        now.hour, now.minute, now.second)


async def batch_create_stockins(db: AsyncSession, stockins_data: list) -> dict:
    """批量创建入库记录"""
    from fastapi_app.services.batch_service import generate_stockin_number

    results = []
    for item in stockins_data:
        try:
            product_id = item.get('product_id')
            customer = item.get('customer', '')
            quantity = item.get('quantity', 0)

            if not all([product_id, customer, quantity]):
                results.append({'success': False, 'error': '缺少必填字段', 'id': item.get('id', '未知')})
                continue

            product = await get_product_for_update(db, product_id)

            stockin_no = await generate_stockin_number(db)
            stockin = StockIn(
                stockin_no=stockin_no, product_id=product_id, customer=customer,
                quantity=int(quantity), stockin_date=datetime.now(), note=item.get('note', '')
            )
            db.add(stockin)
            await db.flush()
            product.current_stock += int(quantity)

            log = InventoryLog(
                product_id=product_id, change_type='备货入库', change_quantity=int(quantity),
                change_date=datetime.now(), customer=customer, related_id=str(stockin.id),
                note=f'批量创建备货 {stockin.stockin_no}'
            )
            db.add(log)
            results.append({'success': True, 'stockin_no': stockin.stockin_no, 'id': stockin.id})
        except Exception as e:
            logger.error(f"批量入库单项失败: {e}")
            results.append({'success': False, 'error': str(e), 'id': item.get('id', '未知')})

    return {'success': True, 'results': results}


async def batch_create_stockouts(db: AsyncSession, stockouts_data: list) -> dict:
    """批量创建出库记录"""
    from fastapi_app.services.batch_service import generate_stockout_number

    results = []
    for item in stockouts_data:
        try:
            product_id = item.get('product_id')
            customer = str(item.get('customer', '')).strip()
            quantity = item.get('quantity', 0)

            if not all([product_id, quantity]):
                results.append({'success': False, 'error': '缺少必填字段', 'id': item.get('id', '未知')})
                continue

            if not customer:
                results.append({'success': False, 'error': '出货必须选择客户', 'id': item.get('id', '未知')})
                continue

            product = await get_product_for_update(db, product_id)

            qty = int(quantity)
            if product.current_stock < qty:
                results.append({'success': False, 'error': f'库存不足，当前库存: {product.current_stock}', 'id': item.get('id', '未知')})
                continue

            # 查找可用订单
            available_orders = (await db.execute(
                select(Order).where(Order.product_id == product_id, Order.customer == customer)
                .order_by(Order.order_date.asc())
            )).scalars().all()

            total_order_qty = sum(o.quantity for o in available_orders)
            # 修复 shipped_qty = 0 的Bug：查询已出货数量
            shipped_result = await db.execute(
                select(func.coalesce(func.sum(StockOut.quantity), 0)).where(
                    StockOut.order_id.in_([o.id for o in available_orders]),
                    StockOut.stockin_id.is_(None)
                )
            )
            shipped_qty = shipped_result.scalar() or 0
            available_qty = max(0, total_order_qty - shipped_qty)

            if available_qty <= 0:
                results.append({'success': False, 'error': f'客户{customer}没有可用订单支持出货', 'id': item.get('id', '未知')})
                continue

            if qty > available_qty:
                results.append({'success': False, 'error': f'出货数量{qty}超过可出货量{available_qty}', 'id': item.get('id', '未知')})
                continue

            # 按FIFO分配订单
            remaining = qty
            for order in available_orders:
                if remaining <= 0:
                    break
                ship_qty = min(remaining, order.quantity)
                stockout_no = await generate_stockout_number(db)
                stockout = StockOut(
                    stockout_no=stockout_no, product_id=product_id, quantity=ship_qty,
                    stockout_date=datetime.now(), customer=customer, order_id=order.id,
                    note=item.get('note', '')
                )
                db.add(stockout)
                await db.flush()
                remaining -= ship_qty

            product.current_stock -= qty
            log = InventoryLog(
                product_id=product_id, change_type='出货', change_quantity=-qty,
                change_date=datetime.now(), customer=customer, related_id='',
                note=f'批量出货：客户{customer}，数量{qty}'
            )
            db.add(log)
            results.append({'success': True, 'id': item.get('id', '未知')})
        except Exception as e:
            logger.error(f"批量出库单项失败: {e}")
            results.append({'success': False, 'error': str(e), 'id': item.get('id', '未知')})

    return {'success': True, 'results': results}
