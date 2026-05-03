"""
库存管理业务逻辑服务

核心 CRUD 和库存计算已统一至 fastapi_app.shared.stock_crud_service。
本服务负责异步适配层：将同步 shared 函数包装为异步调用，
并处理事件发布等 FastAPI 特有逻辑。
"""
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
from fastapi_app.shared_models import InventoryLog, Product, StockIn, StockOut

logger = logging.getLogger(__name__)

async def _create_stockin_record(db: AsyncSession, product_id: int, quantity: int, customer: str, stockin_date: datetime, note: str) -> StockIn:
    if quantity <= 0:
        raise ValueError('入库数量必须大于0')
    stockin = StockIn(stockin_no=await generate_stockin_number(db), product_id=product_id, quantity=quantity, customer=customer, stockin_date=stockin_date, note=note)
    db.add(stockin)
    await db.flush()
    product = await get_product_for_update(db, product_id)
    product.current_stock += quantity
    db.add(InventoryLog(product_id=product_id, change_type='入库', change_quantity=quantity, related_id=str(stockin.id), note=f'入库ID：{stockin.id}'))
    await db.flush()
    return stockin

async def _update_stockin_record(db: AsyncSession, stockin: StockIn, quantity: int, customer: str, stockin_date: datetime, note: str) -> StockIn:
    old_quantity = stockin.quantity
    stockin.quantity = quantity
    stockin.customer = customer
    stockin.stockin_date = stockin_date
    stockin.note = note
    if quantity != old_quantity:
        product = await get_product_for_update(db, stockin.product_id)
        product.current_stock += quantity - old_quantity
        db.add(InventoryLog(product_id=stockin.product_id, change_type='入库修改', change_quantity=quantity - old_quantity, related_id=str(stockin.id), note=f'入库修改ID：{stockin.id}'))
    await db.flush()
    return stockin

async def _delete_stockin_record(db: AsyncSession, stockin: StockIn) -> None:
    if stockin.stockin_stockouts:
        raise ValueError('该入库记录已有出库关联，无法删除')
    product = await get_product_for_update(db, stockin.product_id)
    if product.current_stock - stockin.quantity < 0:
        raise ValueError(f'删除入库记录将导致库存为负数（产品：{product.name}，当前库存：{product.current_stock}，入库数量：{stockin.quantity}）')
    product.current_stock -= stockin.quantity
    db.add(InventoryLog(product_id=stockin.product_id, change_type='入库删除', change_quantity=-stockin.quantity, related_id=str(stockin.id), note=f'入库删除ID：{stockin.id}'))
    await db.delete(stockin)
    await db.flush()

async def _create_stockout_records(db: AsyncSession, product_id: int, quantity: int, customer: str, stockout_date: datetime, note: str, order_type: str='regular', country: str | None=None) -> list[StockOut]:
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

async def _update_stockout_record(db: AsyncSession, stockout: StockOut, new_quantity: int, customer: str, stockout_date: datetime, note: str) -> StockOut:
    if stockout.stockin_id is not None:
        raise ValueError('订单抵扣的出货记录不能直接编辑！请通过订单管理进行修改。')
    old_quantity = stockout.quantity
    product = await get_product_for_update(db, stockout.product_id)
    if product.current_stock + old_quantity < new_quantity:
        raise ValueError('库存不足！')
    if customer and customer.strip():
        shipment_info = await calculate_available_shipment_quantity(db, stockout.product_id, customer)
        available_with_current = shipment_info['available_quantity'] + old_quantity
        if new_quantity > available_with_current:
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

async def _delete_stockout_record(db: AsyncSession, stockout: StockOut) -> None:
    if stockout.stockin_id is not None:
        raise ValueError('订单抵扣的出货记录不能直接删除！请通过订单管理进行修改。')
    product = await get_product_for_update(db, stockout.product_id)
    product.current_stock += stockout.quantity
    db.add(InventoryLog(product_id=stockout.product_id, change_type='出库删除', change_quantity=stockout.quantity, related_id=str(stockout.id), note=f'出库删除ID：{stockout.id}'))
    await db.delete(stockout)
    await db.flush()

async def get_stockins(db: AsyncSession, page: int=1, per_page: int=50) -> dict:
    """获取入库列表（含关联数据，支持分页）"""
    total = (await db.execute(select(func.count(StockIn.id)))).scalar() or 0
    result = await db.execute(select(StockIn).options(joinedload(StockIn.product), selectinload(StockIn.stockin_stockouts)).order_by(StockIn.stockin_date.desc()).offset((page - 1) * per_page).limit(per_page))
    stockins = result.scalars().unique().all()
    data = []
    for s in stockins:
        deducted = sum(so.quantity for so in s.stockin_stockouts) if s.stockin_stockouts else 0
        data.append({'id': s.id, 'stockin_no': s.stockin_no, 'stockin_date': s.stockin_date.strftime('%Y-%m-%d') if s.stockin_date else '', 'customer': s.customer, 'product': {'id': s.product.id, 'name': s.product.name, 'barcode': s.product.barcode or '', 'image': s.product.image or ''} if s.product else None, 'quantity': s.quantity, 'deducted': deducted, 'note': s.note or ''})
    return {'items': data, 'total': total, 'page': page, 'per_page': per_page}

async def create_stockin(db: AsyncSession, product_id: int, quantity: int, customer: str, stockin_date_str: str, note: str) -> dict:
    """创建入库记录"""
    stockin_date = _parse_date_preserve_time(stockin_date_str)
    try:
        stockin = await _create_stockin_record(db, product_id, quantity, customer, stockin_date, note)
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
        await _update_stockin_record(db, stockin_obj, quantity, customer, stockin_date, note)
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
        await _delete_stockin_record(db, stockin_obj)
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
        data.append({'id': s.id, 'stockout_no': s.stockout_no, 'stockout_date': s.stockout_date.strftime('%Y-%m-%d') if s.stockout_date else '', 'customer': s.customer, 'product': {'id': s.product.id, 'name': s.product.name, 'barcode': s.product.barcode or '', 'image': s.product.image or ''} if s.product else None, 'quantity': s.quantity, 'note': s.note or '', 'order_type': s.order.order_type if s.order else 'regular', 'country': s.order.country if s.order and s.order.country else ''})
    return {'items': data, 'total': total, 'page': page, 'per_page': per_page}

async def create_stockout(db: AsyncSession, product_id: int, quantity: int, customer: str, stockout_date_str: str, note: str, order_type: str='regular', country: str | None=None) -> dict:
    """创建出库记录"""
    stockout_date = _parse_date_preserve_time(stockout_date_str)
    try:
        await _create_stockout_records(db, product_id, quantity, customer, stockout_date, note, order_type, country)
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
        await _update_stockout_record(db, stockout_obj, new_quantity, customer, stockout_date, note)
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
    try:
        await _delete_stockout_record(db, stockout_obj)
        await db.commit()
    except (SQLAlchemyError, ValueError):
        await db.rollback()
        raise
    await invalidate_cache('inventory:*')
    await invalidate_cache('orders:*')
    logger.info(f'出库删除成功：{stockout_no}，数量：{stockout_obj.quantity}')

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
        so_ord = int(row.get('order_stockout_qty') or 0)
        o_reg = int(row.get('regular_order_qty') or 0)
        o_cus = int(row.get('custom_order_qty') or 0)
        has_si = bool(row.get('has_stockin'))
        has_o = bool(row.get('has_order'))
        so_total = so_dir + so_ord
        total_qty = si_qty + o_reg + o_cus
        available = max(0, o_reg + o_cus - so_total)
        has_positive = available > 0 or si_qty > 0 or total_qty > 0
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
            inventory_data.append({'customer': customer, 'product_name': pname, 'product_barcode': pbarcode, 'order_quantity': o_reg if o_reg > 0 else '', 'country_orders': country_data, 'stockin_quantity': si_qty if si_qty > 0 else '', 'stockout_quantity': so_total if so_total > 0 else '', 'total_stock': total_qty if total_qty > 0 else ''})
            total_stockin_qty += si_qty
            total_order_qty += o_reg + o_cus
            total_stock += total_qty
    return {'inventory_data': inventory_data, 'total_order_qty': total_order_qty, 'total_stockin_qty': total_stockin_qty, 'total_stock': total_stock, 'all_countries': sorted(all_countries)}

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
    stockin_sql = text('SELECT si.product_id, si.customer, SUM(si.quantity - COALESCE(sub.consumed, 0)) AS stockin_qty, 1 AS has_stockin FROM stock_in si LEFT JOIN (  SELECT stockin_id, SUM(quantity) AS consumed   FROM stock_out WHERE stockin_id IS NOT NULL AND product_id = ANY(:pids)   GROUP BY stockin_id) sub ON sub.stockin_id = si.id WHERE si.product_id = ANY(:pids)' + c + ' GROUP BY si.product_id, si.customer')
    stockout_sql = text('SELECT product_id, customer, SUM(CASE WHEN order_id IS NULL THEN quantity ELSE 0 END) AS direct_stockout_qty, SUM(CASE WHEN order_id IS NOT NULL THEN quantity ELSE 0 END) AS order_stockout_qty FROM stock_out WHERE stockin_id IS NULL AND product_id = ANY(:pids)' + c + ' GROUP BY product_id, customer')
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
        for fld in ('direct_stockout_qty', 'order_stockout_qty', 'regular_order_qty', 'custom_order_qty'):
            merged[k].setdefault(fld, 0)
        merged[k].setdefault('has_order', 0)
        merged[k].setdefault('country_data', '')
    for r in so:
        k = (r['product_id'], r['customer'])
        if k not in merged:
            merged[k] = {'stockin_qty': 0, 'has_stockin': 0, 'regular_order_qty': 0, 'custom_order_qty': 0, 'has_order': 0, 'country_data': ''}
        merged[k]['direct_stockout_qty'] = r['direct_stockout_qty']
        merged[k]['order_stockout_qty'] = r['order_stockout_qty']
    for r in od:
        k = (r['product_id'], r['customer'])
        if k not in merged:
            merged[k] = {'stockin_qty': 0, 'has_stockin': 0, 'direct_stockout_qty': 0, 'order_stockout_qty': 0, 'country_data': ''}
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
                try:
                    async with db.begin_nested():
                        stockin = await _create_stockin_record(db, product_id, quantity, customer, datetime.now(UTC).replace(tzinfo=None), note)
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
                        created = await _create_stockout_records(db, product_id, quantity, customer, datetime.now(UTC).replace(tzinfo=None), note, order_type, country)
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
