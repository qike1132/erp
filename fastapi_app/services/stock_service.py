"""
库存管理业务逻辑服务

核心 CRUD 和库存计算已统一至 fastapi_app.shared.stock_crud_service。
本服务负责异步适配层：将同步 shared 函数包装为异步调用，
并处理事件发布等 FastAPI 特有逻辑。
"""
import asyncio
import logging
from datetime import datetime

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, joinedload

from fastapi_app.shared_models import (
    Product, StockIn, StockOut
)
from fastapi_app.shared.stock_concurrency import get_product_for_update
from fastapi_app.shared.stock_crud_service import (
    create_stockin as _sync_create_stockin,
    update_stockin as _sync_update_stockin,
    delete_stockin as _sync_delete_stockin,
    create_stockout as _sync_create_stockout,
    update_stockout as _sync_update_stockout,
    delete_stockout as _sync_delete_stockout,
    get_inventory as _sync_get_inventory,
)
from fastapi_app.core.database import SyncSessionLocal
from fastapi_app.services.notification_service import publish_stock_event, StockEvent

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
    """创建入库记录 - 委托至共享同步服务"""
    stockin_date = _parse_date_preserve_time(stockin_date_str)

    loop = asyncio.get_running_loop()
    session = SyncSessionLocal()
    try:
        stockin = await loop.run_in_executor(
            None, _sync_create_stockin, session, product_id, quantity,
            customer, stockin_date, note
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    # 发布库存变更事件（数据已提交，事件丢失不影响一致性）
    try:
        product = await get_product_for_update(db, product_id)
        publish_stock_event(StockEvent.STOCK_CHANGED, {
            'product_id': product_id, 'product_name': product.name,
            'change_type': '入库', 'quantity': quantity,
            'current_stock': product.current_stock,
        })
    except Exception as e:
        logger.warning(f'入库事件发布失败（不影响数据）: {e}')
    logger.info(f'入库添加成功：{stockin.stockin_no}，客户：{customer}，产品ID：{product_id}，数量：{quantity}')

    return {'id': stockin.id, 'stockin_no': stockin.stockin_no}


async def update_stockin(db: AsyncSession, stockin_id: int, quantity: int,
                         customer: str, stockin_date_str: str,
                         note: str) -> None:
    """更新入库记录 - 委托至共享同步服务"""
    # 先从异步会话获取 stockin 以解析时间
    stockin_obj = await db.get(StockIn, stockin_id)
    if not stockin_obj:
        raise ValueError('入库记录不存在')
    stockin_date = _parse_date_preserve_time(stockin_date_str, stockin_obj.stockin_date)
    old_quantity = stockin_obj.quantity
    old_stockin_no = stockin_obj.stockin_no

    loop = asyncio.get_running_loop()
    session = SyncSessionLocal()
    try:
        # 从同步会话重新获取 stockin 对象
        sync_stockin = session.execute(
            select(StockIn).where(StockIn.id == stockin_id)
        ).scalar_one_or_none()
        if not sync_stockin:
            raise ValueError('入库记录不存在')
        await loop.run_in_executor(
            None, _sync_update_stockin, session, sync_stockin, quantity,
            customer, stockin_date, note
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    logger.info(f'入库编辑成功：{old_stockin_no}，数量变更：{old_quantity} -> {quantity}')


async def delete_stockin(db: AsyncSession, stockin_id: int) -> None:
    """删除入库记录 - 委托至共享同步服务"""
    stockin_obj = await db.get(StockIn, stockin_id)
    if not stockin_obj:
        raise ValueError('入库记录不存在')
    stockin_no = stockin_obj.stockin_no

    loop = asyncio.get_running_loop()
    session = SyncSessionLocal()
    try:
        sync_stockin = session.execute(
            select(StockIn).where(StockIn.id == stockin_id)
        ).scalar_one_or_none()
        if not sync_stockin:
            raise ValueError('入库记录不存在')
        await loop.run_in_executor(
            None, _sync_delete_stockin, session, sync_stockin
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

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
    """创建出库记录 - 委托至共享同步服务"""
    stockout_date = _parse_date_preserve_time(stockout_date_str)

    loop = asyncio.get_running_loop()
    session = SyncSessionLocal()
    try:
        created = await loop.run_in_executor(
            None, _sync_create_stockout, session, product_id, quantity,
            customer, stockout_date, note, order_type, country
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    # 发布库存变更事件（数据已提交，事件丢失不影响一致性）
    try:
        product = await get_product_for_update(db, product_id)
        publish_stock_event(StockEvent.STOCK_CHANGED, {
            'product_id': product_id, 'product_name': product.name,
            'change_type': '出库', 'quantity': quantity,
            'current_stock': product.current_stock,
        })
    except Exception as e:
        logger.warning(f'出库事件发布失败（不影响数据）: {e}')
    logger.info(f'出库添加成功：产品ID：{product_id}，数量：{quantity}，客户：{customer}')

    return {'quantity': quantity}


async def update_stockout(db: AsyncSession, stockout_id: int, new_quantity: int,
                          customer: str, stockout_date_str: str,
                          note: str) -> None:
    """更新出库记录 - 委托至共享同步服务"""
    stockout_obj = await db.get(StockOut, stockout_id)
    if not stockout_obj:
        raise ValueError('出库记录不存在')

    stockout_date = _parse_date_preserve_time(stockout_date_str)
    old_quantity = stockout_obj.quantity
    old_stockout_no = stockout_obj.stockout_no

    loop = asyncio.get_running_loop()
    session = SyncSessionLocal()
    try:
        sync_stockout = session.execute(
            select(StockOut).where(StockOut.id == stockout_id)
        ).scalar_one_or_none()
        if not sync_stockout:
            raise ValueError('出库记录不存在')
        await loop.run_in_executor(
            None, _sync_update_stockout, session, sync_stockout, new_quantity,
            customer, stockout_date, note
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    logger.info(f'出库编辑成功：{old_stockout_no}，数量变更：{old_quantity} -> {new_quantity}')


async def delete_stockout(db: AsyncSession, stockout_id: int) -> None:
    """删除出库记录 - 委托至共享同步服务"""
    stockout_obj = await db.get(StockOut, stockout_id)
    if not stockout_obj:
        raise ValueError('出库记录不存在')
    stockout_no = stockout_obj.stockout_no

    loop = asyncio.get_running_loop()
    session = SyncSessionLocal()
    try:
        sync_stockout = session.execute(
            select(StockOut).where(StockOut.id == stockout_id)
        ).scalar_one_or_none()
        if not sync_stockout:
            raise ValueError('出库记录不存在')
        await loop.run_in_executor(
            None, _sync_delete_stockout, session, sync_stockout
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    logger.info(f'出库删除成功：{stockout_no}，数量：{stockout_obj.quantity}')


# ==================== 库存查看 ====================

async def get_inventory(db: AsyncSession, search_customer: str = '',
                        search_product: str = '') -> dict:
    """
    获取库存数据 - 委托至共享同步服务
    """
    loop = asyncio.get_running_loop()
    session = SyncSessionLocal()
    try:
        result = await loop.run_in_executor(
            None, _sync_get_inventory, session, search_customer, search_product
        )
        return result
    finally:
        session.close()


# ==================== 内部辅助 ====================

def _parse_date_preserve_time(date_str: str, old_time: datetime | None = None) -> datetime:
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
    """批量创建入库记录 - 委托至共享同步服务"""

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
        loop = asyncio.get_running_loop()
        session = SyncSessionLocal()
        try:
            for orig_idx, item in validated:
                product_id = item.get('product_id')
                customer = str(item.get('customer', '')).strip()
                quantity = int(item.get('quantity', 0))
                note = item.get('note', '')
                try:
                    stockin = await loop.run_in_executor(
                        None, _sync_create_stockin, session, product_id, quantity,
                        customer, datetime.now(), note
                    )
                    results[orig_idx] = {'success': True, 'stockin_no': stockin.stockin_no, 'id': stockin.id}
                except ValueError as e:
                    results[orig_idx] = {'success': False, 'error': str(e), 'id': item.get('id', '未知')}
                except Exception as e:
                    session.rollback()  # 重置 Session 状态，防止后续项级联失败
                    logger.error(f"批量入库单项失败: {e}")
                    results[orig_idx] = {'success': False, 'error': '入库处理失败，请稍后重试', 'id': item.get('id', '未知')}

            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return {'success': True, 'results': results}


async def batch_create_stockouts(db: AsyncSession, stockouts_data: list) -> dict:
    """批量创建出库记录 - 委托至共享同步服务"""

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
        loop = asyncio.get_running_loop()
        session = SyncSessionLocal()
        try:
            for orig_idx, item in validated:
                product_id = item.get('product_id')
                customer = str(item.get('customer', '')).strip()
                quantity = int(item.get('quantity', 0))
                order_type = item.get('order_type', 'regular') or 'regular'
                country = item.get('country', '') or None
                note = item.get('note', '')
                try:
                    created = await loop.run_in_executor(
                        None, _sync_create_stockout, session, product_id, quantity,
                        customer, datetime.now(), note, order_type, country
                    )
                    stockout_nos = [s.stockout_no for s in created] if created else []
                    results[orig_idx] = {'success': True, 'stockout_no': stockout_nos[0] if stockout_nos else '', 'id': item.get('id', '未知')}
                except ValueError as e:
                    results[orig_idx] = {'success': False, 'error': str(e), 'id': item.get('id', '未知')}
                except Exception as e:
                    session.rollback()  # 重置 Session 状态，防止后续项级联失败
                    logger.error(f"批量出库单项失败: {e}")
                    results[orig_idx] = {'success': False, 'error': '出库处理失败，请稍后重试', 'id': item.get('id', '未知')}

            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return {'success': True, 'results': results}
