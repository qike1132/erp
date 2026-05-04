"""
采购计划管理业务逻辑服务（重构版）

主从表结构：PurchasePlan（主表）+ PurchasePlanDetail（明细表）
功能：CRUD、批量上传预览、库存对比（Redis缓存）、出货进度追踪、
月度日历数据、客户汇总统计、计划编号生成。
"""
import calendar
import io
import json
import logging
import uuid
from datetime import date, datetime, timedelta

import openpyxl
from sqlalchemy import and_, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only, selectinload

from fastapi_app.services import customer_service, product_service, stock_service
from fastapi_app.services.plan_utils import (
    build_inventory_map,
    calc_shipment_status,
    last_day_of_month,
    normalize_plan_date,
)
from fastapi_app.shared_models import (
    Customer,
    Product,
    ProductionPlanLog,
    PurchasePlan,
    PurchasePlanDetail,
    ShipmentRecord,
    StagingPurchasePlan,
    StockOut,
)

logger = logging.getLogger(__name__)
INVENTORY_CACHE_PREFIX = 'inventory'
INVENTORY_CACHE_TTL = 300

async def _generate_plan_no(db: AsyncSession) -> str:
    """
    生成计划编号：PP-YYYYMMDD-NNNN
    使用 SELECT ... FOR UPDATE 加行锁防止并发重复编号
    """
    today_str = date.today().strftime('%Y%m%d')
    prefix = f'PP-{today_str}-'
    result = await db.execute(
        select(PurchasePlan.plan_no)
        .where(PurchasePlan.plan_no.like(f'{prefix}%'))
        .order_by(PurchasePlan.plan_no.desc())
        .limit(1)
        .with_for_update()
    )
    max_no = result.scalar()
    if max_no:
        try:
            next_seq = int(max_no.split('-')[-1]) + 1
        except (ValueError, IndexError):
            next_seq = 1
    else:
        next_seq = 1
    return f'{prefix}{next_seq:04d}'

async def get_plan_list(db: AsyncSession, year: int, month: int, customer_id: int=0, status: str='') -> dict:
    """获取指定月份的采购计划主单列表（含明细统计），单次 JOIN 查询"""
    plan_month = f'{year}-{month:02d}'
    conditions = [PurchasePlan.plan_month == plan_month]
    if customer_id:
        conditions.append(PurchasePlan.customer_id == customer_id)
    if status:
        conditions.append(PurchasePlan.status == status)
    result = await db.execute(select(PurchasePlan).options(selectinload(PurchasePlan.details).load_only(PurchasePlanDetail.id, PurchasePlanDetail.quantity, PurchasePlanDetail.plan_id, PurchasePlanDetail.product_name)).where(*conditions).order_by(PurchasePlan.create_time.desc()))
    plans = result.scalars().all()
    # FIFO 分配出货数量
    all_details = [d for p in plans for d in p.details]
    customer_name_map = {p.id: p.customer_name for p in plans}
    shipped_fifo_map = await _get_shipped_fifo_map(db, all_details, customer_name_map)
    plan_list = []
    for plan in plans:
        detail_count = len(plan.details)
        total_quantity = sum(d.quantity for d in plan.details)
        total_shipped = sum(shipped_fifo_map.get(d.id, 0) for d in plan.details)
        plan_list.append({**plan.to_dict(), 'detail_count': detail_count, 'total_quantity': total_quantity, 'total_shipped': total_shipped, 'total_remaining': total_quantity - total_shipped})
    return {'plans': plan_list, 'total': len(plan_list)}

async def get_plan_detail(db: AsyncSession, plan_id: int) -> dict:
    """获取主单 + 明细 + 库存对比 + 出货进度"""
    result = await db.execute(select(PurchasePlan).where(PurchasePlan.id == plan_id))
    plan = result.scalar_one_or_none()
    if not plan:
        raise ValueError('采购计划不存在')
    detail_result = await db.execute(select(PurchasePlanDetail).where(PurchasePlanDetail.plan_id == plan_id).order_by(PurchasePlanDetail.plan_date, PurchasePlanDetail.product_name))
    details = detail_result.scalars().all()
    inventory_map = await _get_inventory_map(db)
    # FIFO 分配出货数量，覆盖缓存的 shipped_qty
    customer_name_map = {plan.id: plan.customer_name}
    shipped_fifo_map = await _get_shipped_fifo_map(db, details, customer_name_map)
    detail_list = []
    for d in details:
        key = (plan.customer_name, d.product_name)
        inv_qty = inventory_map.get(key, 0)
        shp_qty = shipped_fifo_map.get(d.id, 0)
        detail_dict = d.to_dict()
        detail_dict['shipped_qty'] = shp_qty
        detail_dict['remaining_qty'] = d.quantity - shp_qty
        detail_dict['inventory_qty'] = inv_qty
        detail_dict['stock_status'] = _calc_stock_status(d.quantity, inv_qty)
        detail_dict['shipment_status'] = calc_shipment_status(d.quantity, shp_qty)
        detail_list.append(detail_dict)
    return {'plan': plan.to_dict(), 'details': detail_list}

async def create_plan(db: AsyncSession, *, customer_id: int, customer_name: str, plan_month: str, details: list[dict], remark: str='', created_by: str='', upload_batch: str='') -> dict:
    """
    创建采购计划主单 + 明细

    details 格式: [{'product_id': int, 'product_name': str, 'barcode': str,
                     'quantity': int, 'plan_date': str, 'remark': str}]
    """
    customer = await db.execute(select(Customer).where(Customer.id == customer_id))
    if not customer.scalar_one_or_none():
        raise ValueError(f'客户ID {customer_id} 不存在')
    ym_parts = plan_month.split('-')
    if len(ym_parts) != 2:
        raise ValueError(f'月份格式不正确: {plan_month}，请使用 YYYY-MM 格式')
    target_year, target_month = (int(ym_parts[0]), int(ym_parts[1]))
    for d in details:
        plan_date_val = normalize_plan_date(d['plan_date'])
        if plan_date_val.year != target_year or plan_date_val.month != target_month:
            raise ValueError(f"计划日期 {d['plan_date']} 与计划月份 {plan_month} 不一致，不允许跨月")
    barcodes_to_check = list({d.get('barcode', '') for d in details if d.get('barcode')})
    if barcodes_to_check:
        barcode_result = await db.execute(select(Product.barcode).where(Product.barcode.in_(barcodes_to_check)))
        existing_barcodes = {row[0] for row in barcode_result.all()}
        for d in details:
            barcode = d.get('barcode', '')
            if barcode and barcode not in existing_barcodes:
                raise ValueError(f"69码 '{barcode}' 未找到对应产品")
    insufficient = await _check_inventory_realtime(db, [{'barcode': d.get('barcode', ''), 'product_name': d.get('product_name', ''), 'quantity': d['quantity']} for d in details])
    if insufficient:
        errors = '; '.join(f"产品 {it['barcode']}({it['product_name']}) 当前库存 {it['current_stock']} 库存不足 {it['total_quantity'] - it['current_stock']}" for it in insufficient)
        raise ValueError(f'库存不足，无法添加出货计划：{errors}')
    plan = None
    for _attempt in range(3):
        plan_no = await _generate_plan_no(db)
        try:
            async with db.begin_nested():
                plan = PurchasePlan(plan_no=plan_no, plan_month=plan_month, customer_id=customer_id, customer_name=customer_name, status='pending', remark=remark, upload_batch=upload_batch, created_by=created_by)
                db.add(plan)
                await db.flush()
            break
        except IntegrityError:
            if _attempt == 2:
                raise ValueError('单号生成冲突，请勿重复提交') from None
            logger.warning(f'plan_no {plan_no} 冲突，重试({_attempt + 1}/3)')
            continue
    for d in details:
        plan_date_val = normalize_plan_date(d['plan_date'])
        detail = PurchasePlanDetail(plan_id=plan.id, product_id=d['product_id'], product_name=d['product_name'], barcode=d['barcode'], plan_date=plan_date_val, quantity=d['quantity'], shipped_qty=0, remark=d.get('remark', ''))
        db.add(detail)
    await _log_action(db, plan.id, 'create', None, plan.to_dict(), created_by)
    await db.commit()
    logger.info(f'采购计划创建成功：{plan_no} - {customer_name} - {len(details)}条明细')
    return {'plan_id': plan.id, 'plan_no': plan_no}

async def update_plan(db: AsyncSession, plan_id: int, *, created_by: str='', **kwargs) -> dict:
    """更新采购计划主单信息（状态、备注等）"""
    result = await db.execute(select(PurchasePlan).where(PurchasePlan.id == plan_id))
    plan = result.scalar_one_or_none()
    if not plan:
        raise ValueError('采购计划不存在')
    old_data = plan.to_dict()
    for field in ('status', 'remark'):
        if field in kwargs and kwargs[field] is not None:
            setattr(plan, field, kwargs[field])
    await db.flush()
    await _log_action(db, plan.id, 'update', old_data, plan.to_dict(), created_by)
    await db.commit()
    return plan.to_dict()

async def delete_plan(db: AsyncSession, plan_id: int, *, operator: str='') -> None:
    """删除采购计划主单及明细"""
    result = await db.execute(select(PurchasePlan).where(PurchasePlan.id == plan_id))
    plan = result.scalar_one_or_none()
    if not plan:
        raise ValueError('采购计划不存在')
    old_data = plan.to_dict()
    await db.delete(plan)
    await _log_action(db, plan_id, 'delete', old_data, None, operator)
    await db.commit()
    logger.info(f'采购计划删除成功：ID={plan_id}')

async def update_detail(db: AsyncSession, detail_id: int, *, created_by: str='', **kwargs) -> dict:
    """更新单条明细"""
    result = await db.execute(select(PurchasePlanDetail).where(PurchasePlanDetail.id == detail_id))
    detail = result.scalar_one_or_none()
    if not detail:
        raise ValueError('明细记录不存在')
    for field in ('quantity', 'plan_date', 'remark'):
        if field in kwargs and kwargs[field] is not None:
            if field == 'plan_date':
                detail.plan_date = normalize_plan_date(kwargs[field])
            else:
                setattr(detail, field, kwargs[field])
    await db.flush()
    await db.commit()
    return detail.to_dict()

async def delete_detail(db: AsyncSession, detail_id: int) -> None:
    """删除单条明细"""
    result = await db.execute(select(PurchasePlanDetail).where(PurchasePlanDetail.id == detail_id))
    detail = result.scalar_one_or_none()
    if not detail:
        raise ValueError('明细记录不存在')
    await db.delete(detail)
    await db.commit()

async def add_details(db: AsyncSession, plan_id: int, details: list[dict]) -> dict:
    """向主单追加明细"""
    result = await db.execute(select(PurchasePlan).where(PurchasePlan.id == plan_id))
    plan = result.scalar_one_or_none()
    if not plan:
        raise ValueError('采购计划不存在')
    ym_parts = plan.plan_month.split('-')
    target_year, target_month = (int(ym_parts[0]), int(ym_parts[1]))
    added = 0
    for d in details:
        plan_date_val = normalize_plan_date(d['plan_date'])
        if plan_date_val.year != target_year or plan_date_val.month != target_month:
            raise ValueError(f"计划日期 {d['plan_date']} 与主单月份 {plan.plan_month} 不一致")
        detail = PurchasePlanDetail(plan_id=plan_id, product_id=d['product_id'], product_name=d['product_name'], barcode=d['barcode'], plan_date=plan_date_val, quantity=d['quantity'], shipped_qty=0, remark=d.get('remark', ''))
        db.add(detail)
        added += 1
    await db.commit()
    return {'added_count': added}

async def _get_inventory_map(db: AsyncSession) -> dict:
    """
    获取库存查找字典 key=(customer_name, product_name) value=total_stock
    优先从 Redis 缓存读取，缓存未命中则查询 stock_service
    """
    try:
        from utils.redis_cache import redis_cache
        cached = await redis_cache.get(f'{INVENTORY_CACHE_PREFIX}:map')
        if cached is not None:
            return {tuple(k.split('||')): v for k, v in cached.items()}
    except (OSError, ConnectionError, ValueError) as e:
        logger.warning(f'Redis缓存读取失败: {e}')
    try:
        inventory_result = await stock_service.get_inventory(db)
        mapping = build_inventory_map(inventory_result['inventory_data'])
    except (ValueError, TypeError, OSError) as e:
        logger.warning(f'获取库存数据失败: {e}')
        return {}
    try:
        from utils.redis_cache import redis_cache
        cacheable = {f'{k[0]}||{k[1]}': v for k, v in mapping.items()}
        await redis_cache.set(f'{INVENTORY_CACHE_PREFIX}:map', cacheable, timeout=INVENTORY_CACHE_TTL)
    except (OSError, ConnectionError, ValueError) as e:
        logger.warning(f'Redis缓存写入失败: {e}')
    return mapping

def _calc_stock_status(plan_qty: int, inventory_qty: int) -> str:
    """库存状态：充足(>=计划) / 紧张(0<库存<计划) / 无库存(库存=0)"""
    if inventory_qty <= 0:
        return 'no_stock'
    elif inventory_qty >= plan_qty:
        return 'sufficient'
    return 'shortage'

async def _check_inventory_realtime(db: AsyncSession, items: list[dict]) -> list[dict]:
    """
    实时库存校验（直接查数据库，不经过缓存）
    同一 barcode 多条记录会汇总需求量后与库存比较

    参数:
        items: [{'barcode': str, 'product_name': str, 'quantity': int}, ...]
    返回:
        库存不足项列表 [{'barcode': str, 'product_name': str, 'total_quantity': int, 'current_stock': int}, ...]
    """
    if not items:
        return []
    barcodes = list({it['barcode'] for it in items if it.get('barcode')})
    if not barcodes:
        return []
    result = await db.execute(select(Product.id, Product.barcode, Product.name, Product.current_stock).where(Product.barcode.in_(barcodes)))
    product_stock_map = {row.barcode: {'name': row.name, 'current_stock': row.current_stock or 0} for row in result.all()}
    demand_map: dict[str, dict] = {}
    for it in items:
        barcode = it.get('barcode', '')
        if not barcode:
            continue
        if barcode not in demand_map:
            info = product_stock_map.get(barcode)
            demand_map[barcode] = {'product_name': it.get('product_name', '') or (info['name'] if info else ''), 'total_quantity': 0, 'current_stock': info['current_stock'] if info else 0}
        demand_map[barcode]['total_quantity'] += it['quantity']
    insufficient = []
    for barcode, demand in demand_map.items():
        if demand['current_stock'] < demand['total_quantity']:
            insufficient.append({'barcode': barcode, 'product_name': demand['product_name'], 'total_quantity': demand['total_quantity'], 'current_stock': demand['current_stock']})
    return insufficient

async def _get_shipped_fifo_map(db: AsyncSession, plan_details: list, customer_name_map: dict | None = None) -> dict[int, int]:
    """
    FIFO 分配出货数量到计划明细

    对每个 (customer, product) 对：
    1. 查出该客户+产品的所有计划明细（不限当月），按 plan_date ASC 排序
    2. 查出该客户+产品的出货记录（最早计划往前12个月），按 stockout_date ASC 排序
    3. 用累计分配法：出货总量按顺序依次填满最早的计划

    参数:
        plan_details: 当前查询涉及的计划明细列表（PurchasePlanDetail 对象）
        customer_name_map: {plan_id: customer_name} 映射，用于关联主单客户名

    返回: {plan_detail_id: allocated_shipped_qty}
    """
    if not plan_details:
        return {}

    # 收集所有需要查询的 (customer_name, product_name) 对
    keys_needed = set()
    for d in plan_details:
        cname = customer_name_map.get(d.plan_id, '') if customer_name_map else ''
        if cname and d.product_name:
            keys_needed.add((cname, d.product_name))

    if not keys_needed:
        return {}

    # 去重（P1-01: IN列表保护）
    customers = list({k[0] for k in keys_needed})
    product_names = list({k[1] for k in keys_needed})

    # P0-01: 计算日期下限——取所有相关明细中最早的plan_date往前推12个月
    # P1-NEW-01: 转为datetime类型，确保与StockOut.stockout_date(DateTime)比较时索引可用
    earliest_plan_date = min((d.plan_date for d in plan_details if d.plan_date), default=date.today())
    # 用replace减年，避免闰年timedelta(days=365)偏移
    try:
        limit_date = earliest_plan_date.replace(year=earliest_plan_date.year - 1)
    except ValueError:
        limit_date = earliest_plan_date.replace(year=earliest_plan_date.year - 1, day=28)
    stockout_date_limit = datetime(limit_date.year, limit_date.month, limit_date.day)

    # 查询相关主单（P1-03: 用customer_id匹配替代字符串匹配）
    plan_result = await db.execute(
        select(PurchasePlan).where(PurchasePlan.customer_name.in_(customers))
    )
    all_plans = plan_result.scalars().all()
    plan_id_to_customer = {p.id: p.customer_name for p in all_plans}

    # 查询相关主单的所有明细
    relevant_plan_ids = list(plan_id_to_customer.keys())
    if not relevant_plan_ids:
        return {}

    detail_result = await db.execute(
        select(PurchasePlanDetail)
        .where(PurchasePlanDetail.plan_id.in_(relevant_plan_ids))
        .order_by(PurchasePlanDetail.plan_date, PurchasePlanDetail.id)
    )
    all_details = detail_result.scalars().all()

    # 按 (customer_name, product_name) 分组，保持 plan_date ASC 顺序
    details_by_key: dict[tuple, list] = {}
    for d in all_details:
        cname = plan_id_to_customer.get(d.plan_id, '')
        if not cname or not d.product_name:
            continue
        key = (cname, d.product_name)
        if key not in keys_needed:
            continue
        if key not in details_by_key:
            details_by_key[key] = []
        details_by_key[key].append(d)

    # 查出这些客户+产品的出货记录，P0-01: 加12个月日期下限

    stockout_result = await db.execute(
        select(StockOut.customer, Product.name.label('product_name'), StockOut.quantity, StockOut.stockout_date)
        .join(Product, StockOut.product_id == Product.id)
        .where(
            and_(
                StockOut.customer.in_(customers),
                Product.name.in_(product_names),
                StockOut.customer.isnot(None),
                StockOut.customer != '',
                StockOut.stockout_date >= stockout_date_limit,
            )
        )
        .order_by(StockOut.stockout_date, StockOut.id)
    )
    stockout_rows = stockout_result.all()

    # 按 (customer, product_name) 分组，累计出货总量
    shipped_by_key: dict[tuple, int] = {}
    for row in stockout_rows:
        key = (row.customer, row.product_name)
        shipped_by_key[key] = shipped_by_key.get(key, 0) + row.quantity

    # FIFO 分配
    allocated: dict[int, int] = {}
    for key, details in details_by_key.items():
        total_shipped = shipped_by_key.get(key, 0)
        remaining = total_shipped
        for d in details:
            if remaining <= 0:
                allocated[d.id] = 0
            else:
                alloc = min(d.quantity, remaining)
                allocated[d.id] = alloc
                remaining -= alloc

    # 确保所有传入的 plan_details 都有分配值
    for d in plan_details:
        if d.id not in allocated:
            allocated[d.id] = 0

    return allocated

async def get_shipment_progress(db: AsyncSession, plan_id: int) -> dict:
    """获取指定计划的出货进度"""
    result = await db.execute(select(PurchasePlan).where(PurchasePlan.id == plan_id))
    plan = result.scalar_one_or_none()
    if not plan:
        raise ValueError('采购计划不存在')
    detail_result = await db.execute(select(PurchasePlanDetail).where(PurchasePlanDetail.plan_id == plan_id).order_by(PurchasePlanDetail.plan_date, PurchasePlanDetail.product_name))
    details = detail_result.scalars().all()
    # FIFO 分配出货数量
    customer_name_map = {plan.id: plan.customer_name}
    shipped_fifo_map = await _get_shipped_fifo_map(db, details, customer_name_map)
    progress_list = []
    for d in details:
        shp_qty = shipped_fifo_map.get(d.id, 0)
        remaining = d.quantity - shp_qty
        percent = round(shp_qty / d.quantity * 100, 1) if d.quantity > 0 else 0
        progress_list.append({'detail_id': d.id, 'product_name': d.product_name, 'barcode': d.barcode, 'plan_qty': d.quantity, 'shipped_qty': shp_qty, 'remaining_qty': remaining, 'percent': percent, 'shipment_status': calc_shipment_status(d.quantity, shp_qty)})
    return {'details': progress_list}

async def get_shipment_records(db: AsyncSession, plan_id: int) -> list[dict]:
    """获取指定计划关联的出货流水记录（直接从 stock_out 实时查询）"""
    result = await db.execute(select(PurchasePlan).where(PurchasePlan.id == plan_id))
    plan = result.scalar_one_or_none()
    if not plan:
        raise ValueError('采购计划不存在')
    detail_result = await db.execute(select(PurchasePlanDetail.product_name).where(PurchasePlanDetail.plan_id == plan_id).distinct())
    product_names = [row.product_name for row in detail_result.all()]
    if not product_names:
        return []
    # P1-02: 限制计划月份往前12个月，最多500条
    # P1-NEW-02: date_limit基于plan_month而非today，确保历史计划也能看到出货记录
    year, month = map(int, plan.plan_month.split('-'))
    plan_month_start = date(year, month, 1)
    # 减1年，用replace确保精确（避免闰年timedelta偏移）
    # plan_month_start是1号，replace(year)不会触发ValueError
    date_limit_date = plan_month_start.replace(year=plan_month_start.year - 1)
    date_limit = datetime(date_limit_date.year, date_limit_date.month, date_limit_date.day)
    result = await db.execute(select(StockOut.stockout_no, StockOut.stockout_date, StockOut.quantity, StockOut.customer, StockOut.note, Product.name.label('product_name')).join(Product, StockOut.product_id == Product.id).where(and_(StockOut.customer == plan.customer_name, Product.name.in_(product_names), StockOut.customer.isnot(None), StockOut.customer != '', StockOut.stockout_date >= date_limit)).order_by(StockOut.stockout_date.desc(), StockOut.id.desc()).limit(500))
    rows = result.all()
    return [{'shipment_no': row.stockout_no, 'customer_name': row.customer or '', 'product_name': row.product_name, 'quantity': row.quantity, 'shipment_date': row.stockout_date.strftime('%Y-%m-%d') if row.stockout_date else '', 'source_type': 'stockout', 'note': row.note or ''} for row in rows]

async def get_monthly_calendar(db: AsyncSession, year: int, month: int, customer_id: int=0) -> dict:
    """
    月度日历数据：按日期聚合计划，供前端时序面板渲染

    返回:
      plans_by_date: {"2026-04-01": [{...}, ...], ...}
      customers: [{id, name, icon_url}, ...]
    """
    plan_month = f'{year}-{month:02d}'
    conditions = [PurchasePlan.plan_month == plan_month]
    if customer_id:
        conditions.append(PurchasePlan.customer_id == customer_id)
    result = await db.execute(select(PurchasePlan).options(selectinload(PurchasePlan.details)).where(*conditions))
    plans = result.scalars().all()
    inventory_map = await _get_inventory_map(db)
    # 收集所有明细用于 FIFO 分配
    all_details = [d for plan in plans for d in plan.details]
    customer_name_map = {plan.id: plan.customer_name for plan in plans}
    shipped_fifo_map = await _get_shipped_fifo_map(db, all_details, customer_name_map)
    days_in_month = calendar.monthrange(year, month)[1]
    plans_by_date = {}
    customer_set = {}
    for day in range(1, days_in_month + 1):
        d = date(year, month, day)
        plans_by_date[d.isoformat()] = []
    for plan in plans:
        for d in plan.details:
            key = (plan.customer_name, d.product_name)
            inv_qty = inventory_map.get(key, 0)
            shp_qty = shipped_fifo_map.get(d.id, 0)
            date_str = d.plan_date.isoformat() if d.plan_date else ''
            if date_str in plans_by_date:
                plans_by_date[date_str].append({'detail_id': d.id, 'plan_id': plan.id, 'plan_no': plan.plan_no, 'customer_id': plan.customer_id, 'customer_name': plan.customer_name, 'product_name': d.product_name, 'barcode': d.barcode, 'quantity': d.quantity, 'inventory_qty': inv_qty, 'shipped_qty': shp_qty, 'remaining_qty': d.quantity - shp_qty, 'stock_status': _calc_stock_status(d.quantity, inv_qty), 'shipment_status': calc_shipment_status(d.quantity, shp_qty), 'plan_date': date_str})
            if plan.customer_id not in customer_set:
                customer_set[plan.customer_id] = {'id': plan.customer_id, 'name': plan.customer_name, 'icon_url': None}
    return {'year': year, 'month': month, 'days_in_month': days_in_month, 'plans_by_date': plans_by_date, 'customers': list(customer_set.values())}

async def get_customer_summary(db: AsyncSession, year: int, month: int) -> dict:
    """客户维度汇总统计，单次 eager loading 查询"""
    plan_month = f'{year}-{month:02d}'
    result = await db.execute(select(PurchasePlan).options(selectinload(PurchasePlan.details)).where(PurchasePlan.plan_month == plan_month))
    plans = result.scalars().all()
    inventory_map = await _get_inventory_map(db)
    # FIFO 分配出货数量
    all_details = [d for plan in plans for d in plan.details]
    customer_name_map = {plan.id: plan.customer_name for plan in plans}
    shipped_fifo_map = await _get_shipped_fifo_map(db, all_details, customer_name_map)
    # 按 (customer_id, product_name) 聚合，避免同客户不同产品的重复计数
    product_summary: dict[tuple, dict] = {}
    for plan in plans:
        for d in plan.details:
            key = (plan.customer_name, d.product_name)
            inv_qty = inventory_map.get(key, 0)
            shp_qty = shipped_fifo_map.get(d.id, 0)
            product_key = (plan.customer_id, d.product_name)
            if product_key not in product_summary:
                product_summary[product_key] = {'customer_id': plan.customer_id, 'customer_name': plan.customer_name, 'product_name': d.product_name, 'plan_qty': 0, 'inventory_qty': inv_qty, 'shipped_qty': 0, 'remaining_qty': 0, 'warning': False}
            ps = product_summary[product_key]
            ps['plan_qty'] += d.quantity
            ps['shipped_qty'] += shp_qty
            ps['remaining_qty'] += d.quantity - shp_qty
            if _calc_stock_status(d.quantity, inv_qty) != 'sufficient':
                ps['warning'] = True
    # 汇总到客户级别
    summary = {}
    for product_key, ps in product_summary.items():
        cid = ps['customer_id']
        if cid not in summary:
            summary[cid] = {'customer_id': cid, 'customer_name': ps['customer_name'], 'plan_qty': 0, 'inventory_qty': 0, 'shipped_qty': 0, 'remaining_qty': 0, 'warning_count': 0}
        s = summary[cid]
        s['plan_qty'] += ps['plan_qty']
        s['inventory_qty'] += ps['inventory_qty']
        s['shipped_qty'] += ps['shipped_qty']
        s['remaining_qty'] += ps['remaining_qty']
        if ps['warning']:
            s['warning_count'] += 1
    return {'customers': list(summary.values()), 'total_plan_qty': sum(s['plan_qty'] for s in summary.values()), 'total_inventory_qty': sum(s['inventory_qty'] for s in summary.values()), 'total_shipped_qty': sum(s['shipped_qty'] for s in summary.values()), 'total_remaining_qty': sum(s['remaining_qty'] for s in summary.values()), 'warning_count': sum(s['warning_count'] for s in summary.values())}

async def get_inventory_compare(db: AsyncSession, year: int, month: int, customer_id: int=0) -> dict:
    """库存对比数据：每个计划明细的库存状态，单次 eager loading 查询"""
    plan_month = f'{year}-{month:02d}'
    conditions = [PurchasePlan.plan_month == plan_month]
    if customer_id:
        conditions.append(PurchasePlan.customer_id == customer_id)
    result = await db.execute(select(PurchasePlan).options(selectinload(PurchasePlan.details)).where(*conditions))
    plans = result.scalars().all()
    inventory_map = await _get_inventory_map(db)
    compare_list = []
    for plan in plans:
        for d in plan.details:
            key = (plan.customer_name, d.product_name)
            inv_qty = inventory_map.get(key, 0)
            compare_list.append({'detail_id': d.id, 'product_id': d.product_id, 'product_name': d.product_name, 'barcode': d.barcode, 'customer_name': plan.customer_name, 'plan_qty': d.quantity, 'inventory_qty': inv_qty, 'diff': d.quantity - inv_qty, 'stock_status': _calc_stock_status(d.quantity, inv_qty)})
    return {'details': compare_list}

async def upload_excel(db: AsyncSession, file_content: bytes, session_id: str, created_by: str='') -> dict:
    """解析Excel文件，写入暂存表，返回预览数据"""
    batch_id = str(uuid.uuid4())[:8]
    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_content), read_only=True)
    except (OSError, ValueError) as e:
        raise ValueError(f'Excel文件解析失败: {e}') from e
    try:
        ws = wb.active
        rows = list(ws.iter_rows(min_row=2, values_only=True))
    finally:
        wb.close()
    if not rows:
        raise ValueError('Excel文件无数据行')
    detected_month = None
    staging_records = []
    errors = []
    success_count = 0
    for i, row in enumerate(rows, start=2):
        if not row or all(c is None for c in row):
            continue
        try:
            customer_name = str(row[0] or '').strip()
            product_name = str(row[1] or '').strip()
            barcode = str(row[2] or '').strip()
            quantity = int(row[3]) if row[3] else 0
            plan_date_str = str(row[4] or '').strip()
            remark = str(row[5] or '').strip() if len(row) > 5 and row[5] else ''
        except (ValueError, IndexError) as e:
            errors.append(f'第{i}行: 数据格式错误 - {e}')
            continue
        validation_error = ''
        if not customer_name:
            validation_error = '客户名称为空'
        elif not barcode:
            validation_error = '69码为空'
        elif quantity <= 0:
            validation_error = '数量必须为正整数'
        elif not plan_date_str:
            validation_error = '计划日期为空'
        else:
            try:
                parsed_date = normalize_plan_date(plan_date_str)
                row_month = f'{parsed_date.year}-{parsed_date.month:02d}'
                if detected_month is None:
                    detected_month = row_month
                elif row_month != detected_month:
                    validation_error = f'日期月份 {row_month} 与之前行月份 {detected_month} 不一致，不允许跨月'
            except ValueError as e:
                validation_error = str(e)
        record = StagingPurchasePlan(session_id=session_id, customer_name=customer_name, product_name=product_name, barcode=barcode, quantity=quantity, plan_date=normalize_plan_date(plan_date_str) if not validation_error else date.today(), plan_month=detected_month, remark=remark, is_validated=0, validation_error=validation_error, upload_batch_id=batch_id)
        db.add(record)
        staging_records.append(record)
        if not validation_error:
            success_count += 1
    await db.flush()
    await db.commit()
    is_async = len(staging_records) > 500
    return {'batch_id': batch_id, 'total': len(staging_records), 'success_count': success_count, 'error_count': len(errors), 'errors': errors, 'is_async': is_async, 'detected_month': detected_month}

async def get_staging_list(db: AsyncSession, session_id: str) -> list[dict]:
    """获取暂存区预览数据"""
    result = await db.execute(select(StagingPurchasePlan).where(StagingPurchasePlan.session_id == session_id).order_by(StagingPurchasePlan.id))
    records = result.scalars().all()
    return [r.to_dict() for r in records]

async def validate_staging(db: AsyncSession, session_id: str) -> dict:
    """验证暂存数据：检查客户和产品是否存在"""
    result = await db.execute(select(StagingPurchasePlan).where(StagingPurchasePlan.session_id == session_id))
    records = result.scalars().all()
    all_customers = await customer_service.get_customers(db)
    customer_map = {c.name: c for c in all_customers}
    all_products = await product_service.get_products(db)
    barcode_set = {p['barcode'] for p in all_products if p.get('barcode')}
    product_map = {p['barcode']: p for p in all_products if p.get('barcode')}
    valid_count = 0
    error_count = 0
    for record in records:
        errors_list = []
        if record.validation_error:
            errors_list.append(record.validation_error)
        if record.customer_name not in customer_map:
            fuzzy = [c.name for c in all_customers if record.customer_name in c.name]
            hint = f"，相似: {', '.join(fuzzy[:3])}" if fuzzy else ''
            errors_list.append(f"客户 '{record.customer_name}' 不存在{hint}")
        if record.barcode not in barcode_set:
            errors_list.append(f"69码 '{record.barcode}' 未找到产品")
        elif not record.product_name and record.barcode in product_map:
            record.product_name = product_map[record.barcode]['name']
        if errors_list:
            record.is_validated = 0
            record.validation_error = '; '.join(errors_list)
            error_count += 1
        else:
            record.is_validated = 1
            record.validation_error = None
            valid_count += 1
    records_to_check = [r for r in records if r.is_validated and r.barcode in barcode_set]
    if records_to_check:
        insufficient = await _check_inventory_realtime(db, [{'barcode': r.barcode, 'product_name': r.product_name, 'quantity': r.quantity} for r in records_to_check])
        insufficient_map = {it['barcode']: it for it in insufficient}
        for r in records_to_check:
            if r.barcode in insufficient_map:
                it = insufficient_map[r.barcode]
                r.is_validated = 0
                r.validation_error = f"库存不足：当前库存 {it['current_stock']}，库存不足 {it['total_quantity'] - it['current_stock']}"
                valid_count -= 1
                error_count += 1
    await db.flush()
    await db.commit()
    return {'total': len(records), 'valid_count': valid_count, 'error_count': error_count}

async def confirm_staging(db: AsyncSession, session_id: str, batch_id: str='', created_by: str='', selected_ids: list[int]=None) -> dict:
    """
    确认暂存数据，按客户分组创建主单+明细

    同一客户+同月份的记录归入同一个主单
    """
    conditions = [StagingPurchasePlan.session_id == session_id]
    if batch_id:
        conditions.append(StagingPurchasePlan.upload_batch_id == batch_id)
    result = await db.execute(select(StagingPurchasePlan).where(*conditions))
    records = result.scalars().all()
    if not records:
        raise ValueError('暂存区无数据')
    if selected_ids:
        records = [r for r in records if r.id in selected_ids]
    valid_records = [r for r in records if r.is_validated]
    if not valid_records:
        raise ValueError('所有数据验证未通过，无法保存')
    insufficient = await _check_inventory_realtime(db, [{'barcode': r.barcode, 'product_name': r.product_name, 'quantity': r.quantity} for r in valid_records])
    if insufficient:
        errors = '; '.join(f"产品 {it['barcode']}({it['product_name']}) 当前库存 {it['current_stock']} 库存不足 {it['total_quantity'] - it['current_stock']}" for it in insufficient)
        raise ValueError(f'库存不足，无法确认：{errors}')
    groups = {}
    for r in valid_records:
        key = (r.customer_name, r.plan_month or '')
        if key not in groups:
            groups[key] = []
        groups[key].append(r)
    all_customers = await customer_service.get_customers(db)
    customer_id_map = {c.name: c.id for c in all_customers}
    barcodes = list({r.barcode for r in valid_records if r.barcode})
    product_result = await db.execute(select(Product).where(Product.barcode.in_(barcodes)))
    barcode_to_product = {p.barcode: p for p in product_result.scalars().all()}
    created_plans = []
    created_details = 0
    for (customer_name, plan_month), group_records in groups.items():
        if not plan_month:
            continue
        customer_id = customer_id_map.get(customer_name)
        if not customer_id:
            continue
        existing = await db.execute(select(PurchasePlan).where(and_(PurchasePlan.customer_id == customer_id, PurchasePlan.plan_month == plan_month)))
        existing_plan = existing.scalar_one_or_none()
        if existing_plan:
            plan = existing_plan
        else:
            plan = None
            for _attempt in range(3):
                plan_no = await _generate_plan_no(db)
                try:
                    async with db.begin_nested():
                        plan = PurchasePlan(plan_no=plan_no, plan_month=plan_month, customer_id=customer_id, customer_name=customer_name, status='pending', upload_batch=batch_id, created_by=created_by)
                        db.add(plan)
                        await db.flush()
                    break
                except IntegrityError:
                    if _attempt == 2:
                        raise ValueError('单号生成冲突，请勿重复提交') from None
                    logger.warning(f'confirm_staging: plan_no {plan_no} 冲突，重试({_attempt + 1}/3)')
                    continue
        for r in group_records:
            product = barcode_to_product.get(r.barcode)
            detail = PurchasePlanDetail(plan_id=plan.id, product_id=product.id if product else 0, product_name=r.product_name, barcode=r.barcode, plan_date=r.plan_date, quantity=r.quantity, shipped_qty=0, remark=r.remark or '')
            db.add(detail)
            created_details += 1
        created_plans.append({'plan_id': plan.id, 'plan_no': plan.plan_no})
    await db.execute(delete(StagingPurchasePlan).where(*conditions))
    await db.commit()
    logger.info(f'暂存数据确认保存：{len(created_plans)}个主单，{created_details}条明细')
    return {'created_plans': created_plans, 'created_count': created_details, 'skipped_count': len(records) - len(valid_records)}

async def clear_staging(db: AsyncSession, session_id: str) -> None:
    """清空暂存区"""
    await db.execute(delete(StagingPurchasePlan).where(StagingPurchasePlan.session_id == session_id))
    await db.commit()

async def validate_barcode(db: AsyncSession, barcode: str) -> dict:
    """验证69码，返回关联的产品信息"""
    result = await db.execute(select(Product).where(Product.barcode == barcode))
    product = result.scalar_one_or_none()
    if not product:
        return {'valid': False, 'product_name': None, 'message': f"69码 '{barcode}' 未找到对应产品"}
    return {'valid': True, 'product_name': product.name, 'product_id': product.id, 'message': '验证通过'}

async def sync_shipment_records(db: AsyncSession, target_date: date=None) -> dict:
    """
    [DEPRECATED] 从 stock_out 同步出货记录到 shipment_records
    已改用 FIFO 实时查询 stock_out，此函数仅保留兼容性
    """
    if target_date is None:
        target_date = date.today() - timedelta(days=1)
    result = await db.execute(select(StockOut.id, StockOut.stockout_no, StockOut.customer, StockOut.product_id, StockOut.quantity, func.date(StockOut.stockout_date).label('stockout_date'), Product.name.label('product_name')).join(Product, StockOut.product_id == Product.id).where(and_(func.date(StockOut.stockout_date) == target_date, StockOut.customer.isnot(None), StockOut.customer != '')))
    rows = result.all()
    customer_result = await db.execute(select(Customer))
    customers = customer_result.scalars().all()
    customer_id_map = {c.name: c.id for c in customers}
    synced_count = 0
    for row in rows:
        customer_id = customer_id_map.get(row.customer)
        if not customer_id:
            continue
        existing = await db.execute(select(ShipmentRecord).where(ShipmentRecord.shipment_no == row.stockout_no))
        record = existing.scalar_one_or_none()
        if record:
            record.quantity = row.quantity
            record.synced_at = datetime.now()
        else:
            record = ShipmentRecord(shipment_no=row.stockout_no, customer_id=customer_id, customer_name=row.customer, product_id=row.product_id, product_name=row.product_name, quantity=row.quantity, shipment_date=row.stockout_date, source_type='stockout', source_id=row.id, synced_at=datetime.now())
            db.add(record)
        synced_count += 1
    await _refresh_shipped_qty(db, target_date)
    await db.commit()
    logger.info(f'出货记录同步完成：{target_date}，{synced_count}条')
    return {'synced_count': synced_count, 'target_date': target_date.isoformat()}

async def _refresh_shipped_qty(db: AsyncSession, target_date: date) -> None:
    """[DEPRECATED] 刷新受影响月份的计划明细 shipped_qty 缓存（已改用 FIFO 实时查询）"""
    year, month = (target_date.year, target_date.month)
    start = date(year, month, 1)
    end = last_day_of_month(year, month)
    detail_result = await db.execute(select(PurchasePlanDetail).where(and_(PurchasePlanDetail.plan_date >= start, PurchasePlanDetail.plan_date <= end)))
    details = detail_result.scalars().all()
    if not details:
        return
    plan_ids = {d.plan_id for d in details}
    plan_result = await db.execute(select(PurchasePlan).where(PurchasePlan.id.in_(plan_ids)))
    plans = plan_result.scalars().all()
    plan_map = {p.id: p for p in plans}
    shipped_result = await db.execute(select(ShipmentRecord.customer_name, ShipmentRecord.product_name, func.coalesce(func.sum(ShipmentRecord.quantity), 0).label('total_qty')).where(and_(ShipmentRecord.shipment_date >= start, ShipmentRecord.shipment_date <= end)).group_by(ShipmentRecord.customer_name, ShipmentRecord.product_name))
    shipped_map = {(r.customer_name, r.product_name): r.total_qty for r in shipped_result.all()}
    for d in details:
        plan = plan_map.get(d.plan_id)
        if not plan:
            continue
        key = (plan.customer_name, d.product_name)
        d.shipped_qty = shipped_map.get(key, 0)

async def _log_action(db: AsyncSession, plan_id: int, action: str, old_value: dict | None, new_value: dict | None, operator: str) -> None:
    """记录操作日志"""
    log = ProductionPlanLog(plan_id=plan_id, action=action, old_value=json.dumps(old_value, ensure_ascii=False) if old_value else None, new_value=json.dumps(new_value, ensure_ascii=False) if new_value else None, operator=operator)
    db.add(log)
    await db.flush()
