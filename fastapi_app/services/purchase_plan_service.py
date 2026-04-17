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
from datetime import datetime, date, timedelta

import openpyxl
from sqlalchemy import select, func, delete, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fastapi_app.shared_models import (
    PurchasePlan, PurchasePlanDetail, ShipmentRecord,
    StagingPurchasePlan, ProductionPlanLog,
    StockOut, Product, Customer,
)
from fastapi_app.services import product_service, customer_service, stock_service

logger = logging.getLogger(__name__)

# Redis 缓存键前缀
INVENTORY_CACHE_PREFIX = 'inventory'
INVENTORY_CACHE_TTL = 300  # 5分钟


# ==================== 日期边界处理 ====================

def _last_day_of_month(year: int, month: int) -> date:
    """获取月份最后一天"""
    return date(year, month, calendar.monthrange(year, month)[1])


def _normalize_plan_date(date_str: str) -> date:
    """自动校准日期：4月31日→4月30日，2月30日→2月28/29日"""
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        parts = date_str.strip().split('-')
        if len(parts) != 3:
            raise ValueError(f"日期格式不正确: {date_str}，请使用 YYYY-MM-DD 格式")
        y, m = int(parts[0]), int(parts[1])
        d = min(int(parts[2]), calendar.monthrange(y, m)[1])
        return date(y, m, d)


# ==================== 计划编号生成 ====================

async def _generate_plan_no(db: AsyncSession) -> str:
    """
    生成计划编号：PP-YYYYMMDD-NNNN
    NNNN 为当天递增序号，使用 max 而非 count 避免竞态条件
    """
    today_str = date.today().strftime('%Y%m%d')
    prefix = f'PP-{today_str}-'

    # 查询当天最大编号而非count，避免并发时重复
    result = await db.execute(
        select(func.max(PurchasePlan.plan_no))
        .where(PurchasePlan.plan_no.like(f'{prefix}%'))
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


# ==================== 主表 CRUD ====================

async def get_plan_list(db: AsyncSession, year: int, month: int,
                        customer_id: int = 0, status: str = '') -> dict:
    """获取指定月份的采购计划主单列表（含明细统计），单次 JOIN 查询"""
    plan_month = f'{year}-{month:02d}'
    conditions = [PurchasePlan.plan_month == plan_month]
    if customer_id:
        conditions.append(PurchasePlan.customer_id == customer_id)
    if status:
        conditions.append(PurchasePlan.status == status)

    # 单次查询：主表 LEFT JOIN 明细表 + GROUP BY
    result = await db.execute(
        select(
            PurchasePlan,
            func.count(PurchasePlanDetail.id).label('detail_count'),
            func.coalesce(func.sum(PurchasePlanDetail.quantity), 0).label('total_quantity'),
            func.coalesce(func.sum(PurchasePlanDetail.shipped_qty), 0).label('total_shipped'),
        )
        .outerjoin(PurchasePlanDetail, PurchasePlanDetail.plan_id == PurchasePlan.id)
        .where(*conditions)
        .group_by(PurchasePlan.id)
        .order_by(PurchasePlan.create_time.desc())
    )
    rows = result.all()

    plan_list = []
    for plan, detail_count, total_quantity, total_shipped in rows:
        plan_list.append({
            **plan.to_dict(),
            'detail_count': detail_count,
            'total_quantity': total_quantity,
            'total_shipped': total_shipped,
            'total_remaining': total_quantity - total_shipped,
        })

    return {
        'plans': plan_list,
        'total': len(plan_list),
    }


async def get_plan_detail(db: AsyncSession, plan_id: int) -> dict:
    """获取主单 + 明细 + 库存对比 + 出货进度"""
    result = await db.execute(
        select(PurchasePlan).where(PurchasePlan.id == plan_id)
    )
    plan = result.scalar_one_or_none()
    if not plan:
        raise ValueError('采购计划不存在')

    # 获取明细
    detail_result = await db.execute(
        select(PurchasePlanDetail)
        .where(PurchasePlanDetail.plan_id == plan_id)
        .order_by(PurchasePlanDetail.plan_date, PurchasePlanDetail.product_name)
    )
    details = detail_result.scalars().all()

    # 获取库存
    inventory_map = await _get_inventory_map(db)

    # 获取出货
    year, month = map(int, plan.plan_month.split('-'))
    shipped_map = await _get_shipped_map(db, year, month)

    detail_list = []
    for d in details:
        key = (plan.customer_name, d.product_name)
        inv_qty = inventory_map.get(key, 0)
        shp_qty = shipped_map.get(key, 0)

        # 更新 shipped_qty 缓存
        if d.shipped_qty != shp_qty:
            d.shipped_qty = shp_qty

        detail_list.append({
            **d.to_dict(),
            'inventory_qty': inv_qty,
            'stock_status': _calc_stock_status(d.quantity, inv_qty),
            'shipment_status': _calc_shipment_status(d.quantity, shp_qty),
        })

    await db.flush()

    return {
        'plan': plan.to_dict(),
        'details': detail_list,
    }


async def create_plan(db: AsyncSession, *, customer_id: int, customer_name: str,
                      plan_month: str, details: list[dict],
                      remark: str = '', created_by: str = '',
                      upload_batch: str = '') -> dict:
    """
    创建采购计划主单 + 明细

    details 格式: [{'product_id': int, 'product_name': str, 'barcode': str,
                     'quantity': int, 'plan_date': str, 'remark': str}]
    """
    # 验证客户
    customer = await db.execute(
        select(Customer).where(Customer.id == customer_id)
    )
    if not customer.scalar_one_or_none():
        raise ValueError(f"客户ID {customer_id} 不存在")

    # 月份一致性校验：所有 plan_date 的月份必须与 plan_month 一致
    ym_parts = plan_month.split('-')
    if len(ym_parts) != 2:
        raise ValueError(f"月份格式不正确: {plan_month}，请使用 YYYY-MM 格式")
    target_year, target_month = int(ym_parts[0]), int(ym_parts[1])

    for d in details:
        plan_date_val = _normalize_plan_date(d['plan_date'])
        if plan_date_val.year != target_year or plan_date_val.month != target_month:
            raise ValueError(f"计划日期 {d['plan_date']} 与计划月份 {plan_month} 不一致，不允许跨月")

    # 验证69码
    for d in details:
        barcode = d.get('barcode', '')
        products = await product_service.search_products(db, barcode)
        if not products:
            raise ValueError(f"69码 '{barcode}' 未找到对应产品")

    # 生成计划编号
    plan_no = await _generate_plan_no(db)

    # 创建主单
    plan = PurchasePlan(
        plan_no=plan_no,
        plan_month=plan_month,
        customer_id=customer_id,
        customer_name=customer_name,
        status='pending',
        remark=remark,
        upload_batch=upload_batch,
        created_by=created_by,
    )
    db.add(plan)
    await db.flush()

    # 创建明细
    for d in details:
        plan_date_val = _normalize_plan_date(d['plan_date'])
        detail = PurchasePlanDetail(
            plan_id=plan.id,
            product_id=d['product_id'],
            product_name=d['product_name'],
            barcode=d['barcode'],
            plan_date=plan_date_val,
            quantity=d['quantity'],
            shipped_qty=0,
            remark=d.get('remark', ''),
        )
        db.add(detail)

    await _log_action(db, plan.id, 'create', None, plan.to_dict(), created_by)
    await db.commit()
    logger.info(f'采购计划创建成功：{plan_no} - {customer_name} - {len(details)}条明细')

    return {'plan_id': plan.id, 'plan_no': plan_no}


async def update_plan(db: AsyncSession, plan_id: int, *, created_by: str = '', **kwargs) -> dict:
    """更新采购计划主单信息（状态、备注等）"""
    result = await db.execute(
        select(PurchasePlan).where(PurchasePlan.id == plan_id)
    )
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


async def delete_plan(db: AsyncSession, plan_id: int, *, operator: str = '') -> None:
    """删除采购计划主单及明细"""
    result = await db.execute(
        select(PurchasePlan).where(PurchasePlan.id == plan_id)
    )
    plan = result.scalar_one_or_none()
    if not plan:
        raise ValueError('采购计划不存在')

    old_data = plan.to_dict()
    # 级联删除明细（CASCADE 已配置）
    await db.delete(plan)
    await _log_action(db, plan_id, 'delete', old_data, None, operator)
    await db.commit()
    logger.info(f'采购计划删除成功：ID={plan_id}')


# ==================== 明细 CRUD ====================

async def update_detail(db: AsyncSession, detail_id: int, *, created_by: str = '', **kwargs) -> dict:
    """更新单条明细"""
    result = await db.execute(
        select(PurchasePlanDetail).where(PurchasePlanDetail.id == detail_id)
    )
    detail = result.scalar_one_or_none()
    if not detail:
        raise ValueError('明细记录不存在')

    for field in ('quantity', 'plan_date', 'remark'):
        if field in kwargs and kwargs[field] is not None:
            if field == 'plan_date':
                detail.plan_date = _normalize_plan_date(kwargs[field])
            else:
                setattr(detail, field, kwargs[field])

    await db.flush()
    await db.commit()
    return detail.to_dict()


async def delete_detail(db: AsyncSession, detail_id: int) -> None:
    """删除单条明细"""
    result = await db.execute(
        select(PurchasePlanDetail).where(PurchasePlanDetail.id == detail_id)
    )
    detail = result.scalar_one_or_none()
    if not detail:
        raise ValueError('明细记录不存在')
    await db.delete(detail)
    await db.commit()


async def add_details(db: AsyncSession, plan_id: int, details: list[dict]) -> dict:
    """向主单追加明细"""
    result = await db.execute(
        select(PurchasePlan).where(PurchasePlan.id == plan_id)
    )
    plan = result.scalar_one_or_none()
    if not plan:
        raise ValueError('采购计划不存在')

    # 月份一致性校验
    ym_parts = plan.plan_month.split('-')
    target_year, target_month = int(ym_parts[0]), int(ym_parts[1])

    added = 0
    for d in details:
        plan_date_val = _normalize_plan_date(d['plan_date'])
        if plan_date_val.year != target_year or plan_date_val.month != target_month:
            raise ValueError(f"计划日期 {d['plan_date']} 与主单月份 {plan.plan_month} 不一致")

        detail = PurchasePlanDetail(
            plan_id=plan_id,
            product_id=d['product_id'],
            product_name=d['product_name'],
            barcode=d['barcode'],
            plan_date=plan_date_val,
            quantity=d['quantity'],
            shipped_qty=0,
            remark=d.get('remark', ''),
        )
        db.add(detail)
        added += 1

    await db.commit()
    return {'added_count': added}


# ==================== 库存对比 ====================

async def _get_inventory_map(db: AsyncSession) -> dict:
    """
    获取库存查找字典 key=(customer_name, product_name) value=total_stock
    优先从 Redis 缓存读取，缓存未命中则查询 stock_service
    """
    try:
        from utils.redis_cache import redis_cache
        from fastapi.concurrency import run_in_threadpool
        cached = await run_in_threadpool(redis_cache.get, f'{INVENTORY_CACHE_PREFIX}:map')
        if cached is not None:
            return cached
    except Exception as e:
        logger.warning(f'Redis缓存读取失败: {e}')

    try:
        inventory_result = await stock_service.get_inventory(db)
        mapping = _build_inventory_map(inventory_result['inventory_data'])
    except Exception as e:
        logger.warning(f'获取库存数据失败: {e}')
        return {}

    # 写入 Redis 缓存
    try:
        from utils.redis_cache import redis_cache
        from fastapi.concurrency import run_in_threadpool
        await run_in_threadpool(redis_cache.set, f'{INVENTORY_CACHE_PREFIX}:map', mapping, timeout=INVENTORY_CACHE_TTL)
    except Exception as e:
        logger.warning(f'Redis缓存写入失败: {e}')

    return mapping


def _build_inventory_map(inventory_data: list) -> dict:
    """构建库存查找字典"""
    mapping = {}
    for item in inventory_data:
        key = (item['customer'], item['product_name'])
        stock = item.get('total_stock', 0) or 0
        if isinstance(stock, str):
            try:
                stock = int(stock)
            except (ValueError, TypeError):
                stock = 0
        mapping[key] = mapping.get(key, 0) + stock
    return mapping


def _calc_stock_status(plan_qty: int, inventory_qty: int) -> str:
    """库存状态：充足(>=计划) / 紧张(0<库存<计划) / 无库存(库存=0)"""
    if inventory_qty <= 0:
        return 'no_stock'
    elif inventory_qty >= plan_qty:
        return 'sufficient'
    return 'shortage'


def _calc_shipment_status(plan_qty: int, shipped_qty: int) -> str:
    """出货状态: completed/partial/pending"""
    if shipped_qty >= plan_qty:
        return 'completed'
    elif shipped_qty > 0:
        return 'partial'
    return 'pending'


# ==================== 出货进度 ====================

async def _get_shipped_map(db: AsyncSession, year: int, month: int) -> dict:
    """
    获取当月出货数据，优先从 shipment_records 读取，降级到 stock_out
    返回: {(customer_name, product_name): total_shipped_qty}
    """
    # 先从 shipment_records 读取
    start = date(year, month, 1)
    end = _last_day_of_month(year, month)

    result = await db.execute(
        select(
            ShipmentRecord.customer_name,
            ShipmentRecord.product_name,
            func.coalesce(func.sum(ShipmentRecord.quantity), 0).label('total_qty'),
        )
        .where(and_(
            ShipmentRecord.shipment_date >= start,
            ShipmentRecord.shipment_date <= end,
        ))
        .group_by(ShipmentRecord.customer_name, ShipmentRecord.product_name)
    )
    rows = result.all()

    if rows:
        return {(row.customer_name, row.product_name): row.total_qty for row in rows}

    # 降级：直接查 stock_out
    return await _calc_shipped_from_stockout(db, year, month)


async def _calc_shipped_from_stockout(db: AsyncSession, year: int, month: int) -> dict:
    """直接从 stock_out 表计算出货量（降级方案）"""
    start = date(year, month, 1)
    end = _last_day_of_month(year, month)

    result = await db.execute(
        select(
            StockOut.customer,
            Product.name.label('product_name'),
            func.coalesce(func.sum(StockOut.quantity), 0).label('total_qty'),
        )
        .join(Product, StockOut.product_id == Product.id)
        .where(and_(
            func.date(StockOut.stockout_date) >= start,
            func.date(StockOut.stockout_date) <= end,
            StockOut.customer.isnot(None),
            StockOut.customer != '',
        ))
        .group_by(StockOut.customer, Product.name)
    )

    return {(row.customer, row.product_name): row.total_qty for row in result.all()}


async def get_shipment_progress(db: AsyncSession, plan_id: int) -> dict:
    """获取指定计划的出货进度"""
    result = await db.execute(
        select(PurchasePlan).where(PurchasePlan.id == plan_id)
    )
    plan = result.scalar_one_or_none()
    if not plan:
        raise ValueError('采购计划不存在')

    detail_result = await db.execute(
        select(PurchasePlanDetail)
        .where(PurchasePlanDetail.plan_id == plan_id)
        .order_by(PurchasePlanDetail.plan_date, PurchasePlanDetail.product_name)
    )
    details = detail_result.scalars().all()

    progress_list = []
    for d in details:
        remaining = d.quantity - d.shipped_qty
        percent = round(d.shipped_qty / d.quantity * 100, 1) if d.quantity > 0 else 0
        progress_list.append({
            'detail_id': d.id,
            'product_name': d.product_name,
            'barcode': d.barcode,
            'plan_qty': d.quantity,
            'shipped_qty': d.shipped_qty,
            'remaining_qty': remaining,
            'percent': percent,
            'shipment_status': _calc_shipment_status(d.quantity, d.shipped_qty),
        })

    return {'details': progress_list}


# ==================== 月度日历数据 ====================

async def get_monthly_calendar(db: AsyncSession, year: int, month: int,
                                customer_id: int = 0) -> dict:
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

    # 一次性加载主表+明细（eager loading）
    result = await db.execute(
        select(PurchasePlan)
        .options(selectinload(PurchasePlan.details))
        .where(*conditions)
    )
    plans = result.scalars().all()

    # 获取库存和出货
    inventory_map = await _get_inventory_map(db)
    shipped_map = await _get_shipped_map(db, year, month)

    # 初始化日历结构
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
            shp_qty = shipped_map.get(key, 0)

            date_str = d.plan_date.isoformat() if d.plan_date else ''
            if date_str in plans_by_date:
                plans_by_date[date_str].append({
                    'detail_id': d.id,
                    'plan_id': plan.id,
                    'plan_no': plan.plan_no,
                    'customer_id': plan.customer_id,
                    'customer_name': plan.customer_name,
                    'product_name': d.product_name,
                    'barcode': d.barcode,
                    'quantity': d.quantity,
                    'inventory_qty': inv_qty,
                    'shipped_qty': shp_qty,
                    'remaining_qty': d.quantity - shp_qty,
                    'stock_status': _calc_stock_status(d.quantity, inv_qty),
                    'shipment_status': _calc_shipment_status(d.quantity, shp_qty),
                    'plan_date': date_str,
                })

            if plan.customer_id not in customer_set:
                customer_set[plan.customer_id] = {
                    'id': plan.customer_id,
                    'name': plan.customer_name,
                    'icon_url': None,
                }

    return {
        'year': year,
        'month': month,
        'days_in_month': days_in_month,
        'plans_by_date': plans_by_date,
        'customers': list(customer_set.values()),
    }


# ==================== 客户汇总 ====================

async def get_customer_summary(db: AsyncSession, year: int, month: int) -> dict:
    """客户维度汇总统计，单次 eager loading 查询"""
    plan_month = f'{year}-{month:02d}'

    result = await db.execute(
        select(PurchasePlan)
        .options(selectinload(PurchasePlan.details))
        .where(PurchasePlan.plan_month == plan_month)
    )
    plans = result.scalars().all()

    inventory_map = await _get_inventory_map(db)
    shipped_map = await _get_shipped_map(db, year, month)

    summary = {}
    for plan in plans:
        for d in plan.details:
            key = (plan.customer_name, d.product_name)
            inv_qty = inventory_map.get(key, 0)
            shp_qty = shipped_map.get(key, 0)
            stock_status = _calc_stock_status(d.quantity, inv_qty)

            cid = plan.customer_id
            if cid not in summary:
                summary[cid] = {
                    'customer_id': cid,
                    'customer_name': plan.customer_name,
                    'plan_qty': 0,
                    'inventory_qty': 0,
                    'shipped_qty': 0,
                    'remaining_qty': 0,
                    'warning_count': 0,
                }
            s = summary[cid]
            s['plan_qty'] += d.quantity
            s['inventory_qty'] += inv_qty
            s['shipped_qty'] += shp_qty
            s['remaining_qty'] += (d.quantity - shp_qty)
            if stock_status != 'sufficient':
                s['warning_count'] += 1

    return {
        'customers': list(summary.values()),
        'total_plan_qty': sum(s['plan_qty'] for s in summary.values()),
        'total_inventory_qty': sum(s['inventory_qty'] for s in summary.values()),
        'total_shipped_qty': sum(s['shipped_qty'] for s in summary.values()),
        'total_remaining_qty': sum(s['remaining_qty'] for s in summary.values()),
        'warning_count': sum(s['warning_count'] for s in summary.values()),
    }


# ==================== 库存对比接口 ====================

async def get_inventory_compare(db: AsyncSession, year: int, month: int,
                                 customer_id: int = 0) -> dict:
    """库存对比数据：每个计划明细的库存状态，单次 eager loading 查询"""
    plan_month = f'{year}-{month:02d}'
    conditions = [PurchasePlan.plan_month == plan_month]
    if customer_id:
        conditions.append(PurchasePlan.customer_id == customer_id)

    result = await db.execute(
        select(PurchasePlan)
        .options(selectinload(PurchasePlan.details))
        .where(*conditions)
    )
    plans = result.scalars().all()

    inventory_map = await _get_inventory_map(db)

    compare_list = []
    for plan in plans:
        for d in plan.details:
            key = (plan.customer_name, d.product_name)
            inv_qty = inventory_map.get(key, 0)
            compare_list.append({
                'detail_id': d.id,
                'product_id': d.product_id,
                'product_name': d.product_name,
                'barcode': d.barcode,
                'customer_name': plan.customer_name,
                'plan_qty': d.quantity,
                'inventory_qty': inv_qty,
                'diff': d.quantity - inv_qty,
                'stock_status': _calc_stock_status(d.quantity, inv_qty),
            })

    return {'details': compare_list}


# ==================== 批量上传与预览 ====================

async def upload_excel(db: AsyncSession, file_content: bytes,
                       session_id: str, created_by: str = '') -> dict:
    """解析Excel文件，写入暂存表，返回预览数据"""
    batch_id = str(uuid.uuid4())[:8]

    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_content), read_only=True)
    except Exception as e:
        raise ValueError(f"Excel文件解析失败: {e}")

    try:
        ws = wb.active
        rows = list(ws.iter_rows(min_row=2, values_only=True))
    finally:
        wb.close()

    if not rows:
        raise ValueError("Excel文件无数据行")

    # 月份一致性收集
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
            errors.append(f"第{i}行: 数据格式错误 - {e}")
            continue

        # 基础验证
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
                parsed_date = _normalize_plan_date(plan_date_str)
                row_month = f'{parsed_date.year}-{parsed_date.month:02d}'
                if detected_month is None:
                    detected_month = row_month
                elif row_month != detected_month:
                    validation_error = f'日期月份 {row_month} 与之前行月份 {detected_month} 不一致，不允许跨月'
            except ValueError as e:
                validation_error = str(e)

        record = StagingPurchasePlan(
            session_id=session_id,
            customer_name=customer_name,
            product_name=product_name,
            barcode=barcode,
            quantity=quantity,
            plan_date=_normalize_plan_date(plan_date_str) if not validation_error else date.today(),
            plan_month=detected_month,
            remark=remark,
            is_validated=0,
            validation_error=validation_error,
            upload_batch_id=batch_id,
        )
        db.add(record)
        staging_records.append(record)
        if not validation_error:
            success_count += 1

    await db.flush()

    # 返回结果（行数>500时标记需走 Celery）
    is_async = len(staging_records) > 500

    return {
        'batch_id': batch_id,
        'total': len(staging_records),
        'success_count': success_count,
        'error_count': len(errors),
        'errors': errors,
        'is_async': is_async,
        'detected_month': detected_month,
    }


async def get_staging_list(db: AsyncSession, session_id: str) -> list[dict]:
    """获取暂存区预览数据"""
    result = await db.execute(
        select(StagingPurchasePlan)
        .where(StagingPurchasePlan.session_id == session_id)
        .order_by(StagingPurchasePlan.id)
    )
    records = result.scalars().all()
    return [r.to_dict() for r in records]


async def validate_staging(db: AsyncSession, session_id: str) -> dict:
    """验证暂存数据：检查客户和产品是否存在"""
    result = await db.execute(
        select(StagingPurchasePlan)
        .where(StagingPurchasePlan.session_id == session_id)
    )
    records = result.scalars().all()

    # 预加载客户和产品
    all_customers = await customer_service.get_customers(db)
    customer_map = {c.name: c for c in all_customers}

    all_products = await product_service.get_products(db)
    barcode_set = {p.barcode for p in all_products if p.barcode}
    product_map = {p.barcode: p for p in all_products if p.barcode}

    valid_count = 0
    error_count = 0

    for record in records:
        errors_list = []
        if record.validation_error:
            errors_list.append(record.validation_error)

        # 客户验证
        if record.customer_name not in customer_map:
            # 模糊匹配提示
            fuzzy = [c.name for c in all_customers if record.customer_name in c.name]
            hint = f"，相似: {', '.join(fuzzy[:3])}" if fuzzy else ''
            errors_list.append(f"客户 '{record.customer_name}' 不存在{hint}")

        # 69码验证
        if record.barcode not in barcode_set:
            errors_list.append(f"69码 '{record.barcode}' 未找到产品")
        elif not record.product_name and record.barcode in product_map:
            record.product_name = product_map[record.barcode].name

        if errors_list:
            record.is_validated = 0
            record.validation_error = '; '.join(errors_list)
            error_count += 1
        else:
            record.is_validated = 1
            record.validation_error = None
            valid_count += 1

    await db.flush()

    return {
        'total': len(records),
        'valid_count': valid_count,
        'error_count': error_count,
    }


async def confirm_staging(db: AsyncSession, session_id: str,
                           batch_id: str = '', created_by: str = '',
                           selected_ids: list[int] = None) -> dict:
    """
    确认暂存数据，按客户分组创建主单+明细

    同一客户+同月份的记录归入同一个主单
    """
    conditions = [StagingPurchasePlan.session_id == session_id]
    if batch_id:
        conditions.append(StagingPurchasePlan.upload_batch_id == batch_id)

    result = await db.execute(
        select(StagingPurchasePlan).where(*conditions)
    )
    records = result.scalars().all()

    if not records:
        raise ValueError('暂存区无数据')

    # 过滤选中的记录
    if selected_ids:
        records = [r for r in records if r.id in selected_ids]

    # 仅确认验证通过的记录
    valid_records = [r for r in records if r.is_validated]
    if not valid_records:
        raise ValueError('所有数据验证未通过，无法保存')

    # 按客户+月份分组
    groups = {}
    for r in valid_records:
        key = (r.customer_name, r.plan_month or '')
        if key not in groups:
            groups[key] = []
        groups[key].append(r)

    # 获取客户 ID 映射
    all_customers = await customer_service.get_customers(db)
    customer_id_map = {c.name: c.id for c in all_customers}

    # 批量获取产品映射（一次性查询所有 barcode）
    barcodes = list({r.barcode for r in valid_records if r.barcode})
    product_result = await db.execute(
        select(Product).where(Product.barcode.in_(barcodes))
    )
    barcode_to_product = {p.barcode: p for p in product_result.scalars().all()}

    created_plans = []
    created_details = 0

    for (customer_name, plan_month), group_records in groups.items():
        if not plan_month:
            continue

        customer_id = customer_id_map.get(customer_name)
        if not customer_id:
            continue

        # 检查该客户+月份是否已有主单
        existing = await db.execute(
            select(PurchasePlan).where(and_(
                PurchasePlan.customer_id == customer_id,
                PurchasePlan.plan_month == plan_month,
            ))
        )
        existing_plan = existing.scalar_one_or_none()

        if existing_plan:
            # 追加明细到已有主单
            plan = existing_plan
        else:
            # 创建新主单
            plan_no = await _generate_plan_no(db)
            plan = PurchasePlan(
                plan_no=plan_no,
                plan_month=plan_month,
                customer_id=customer_id,
                customer_name=customer_name,
                status='pending',
                upload_batch=batch_id,
                created_by=created_by,
            )
            db.add(plan)
            await db.flush()

        # 创建明细
        for r in group_records:
            product = barcode_to_product.get(r.barcode)
            detail = PurchasePlanDetail(
                plan_id=plan.id,
                product_id=product.id if product else 0,
                product_name=r.product_name,
                barcode=r.barcode,
                plan_date=r.plan_date,
                quantity=r.quantity,
                shipped_qty=0,
                remark=r.remark or '',
            )
            db.add(detail)
            created_details += 1

        created_plans.append({'plan_id': plan.id, 'plan_no': plan.plan_no})

    # 清空该批暂存数据
    await db.execute(
        delete(StagingPurchasePlan).where(*conditions)
    )

    await db.commit()
    logger.info(f'暂存数据确认保存：{len(created_plans)}个主单，{created_details}条明细')

    return {
        'created_plans': created_plans,
        'created_count': created_details,
        'skipped_count': len(records) - len(valid_records),
    }


async def clear_staging(db: AsyncSession, session_id: str) -> None:
    """清空暂存区"""
    await db.execute(
        delete(StagingPurchasePlan).where(StagingPurchasePlan.session_id == session_id)
    )
    await db.commit()


# ==================== 69码验证 ====================

async def validate_barcode(db: AsyncSession, barcode: str) -> dict:
    """验证69码，返回关联的产品信息"""
    products = await product_service.search_products(db, barcode)
    if not products:
        return {'valid': False, 'product_name': None, 'message': f"69码 '{barcode}' 未找到对应产品"}

    exact = [p for p in products if p.get('barcode') == barcode]
    p = exact[0] if exact else products[0]
    return {'valid': True, 'product_name': p['name'], 'product_id': p.get('id'), 'message': '验证通过'}


# ==================== 出货同步 ====================

async def sync_shipment_records(db: AsyncSession, target_date: date = None) -> dict:
    """
    从 stock_out 同步出货记录到 shipment_records

    target_date: 同步指定日期的数据，默认为昨天
    """
    if target_date is None:
        target_date = date.today() - timedelta(days=1)

    # 查询目标日期的 stock_out 记录
    result = await db.execute(
        select(
            StockOut.id,
            StockOut.stockout_no,
            StockOut.customer,
            StockOut.product_id,
            StockOut.quantity,
            func.date(StockOut.stockout_date).label('stockout_date'),
            Product.name.label('product_name'),
        )
        .join(Product, StockOut.product_id == Product.id)
        .where(and_(
            func.date(StockOut.stockout_date) == target_date,
            StockOut.customer.isnot(None),
            StockOut.customer != '',
        ))
    )
    rows = result.all()

    # 获取客户 ID 映射
    customer_result = await db.execute(select(Customer))
    customers = customer_result.scalars().all()
    customer_id_map = {c.name: c.id for c in customers}

    synced_count = 0
    for row in rows:
        customer_id = customer_id_map.get(row.customer)
        if not customer_id:
            continue

        # UPSERT：shipment_no 唯一键冲突则更新
        existing = await db.execute(
            select(ShipmentRecord).where(ShipmentRecord.shipment_no == row.stockout_no)
        )
        record = existing.scalar_one_or_none()

        if record:
            record.quantity = row.quantity
            record.synced_at = datetime.now()
        else:
            record = ShipmentRecord(
                shipment_no=row.stockout_no,
                customer_id=customer_id,
                customer_name=row.customer,
                product_id=row.product_id,
                product_name=row.product_name,
                quantity=row.quantity,
                shipment_date=row.stockout_date,
                source_type='stockout',
                source_id=row.id,
                synced_at=datetime.now(),
            )
            db.add(record)

        synced_count += 1

    # 更新 purchase_plan_details.shipped_qty
    await _refresh_shipped_qty(db, target_date)

    await db.commit()
    logger.info(f'出货记录同步完成：{target_date}，{synced_count}条')

    return {'synced_count': synced_count, 'target_date': target_date.isoformat()}


async def _refresh_shipped_qty(db: AsyncSession, target_date: date) -> None:
    """刷新受影响月份的计划明细 shipped_qty"""
    year, month = target_date.year, target_date.month
    start = date(year, month, 1)
    end = _last_day_of_month(year, month)

    # 查询该月所有明细
    detail_result = await db.execute(
        select(PurchasePlanDetail)
        .where(and_(
            PurchasePlanDetail.plan_date >= start,
            PurchasePlanDetail.plan_date <= end,
        ))
    )
    details = detail_result.scalars().all()

    if not details:
        return

    # 获取客户映射
    plan_ids = set(d.plan_id for d in details)
    plan_result = await db.execute(
        select(PurchasePlan).where(PurchasePlan.id.in_(plan_ids))
    )
    plans = plan_result.scalars().all()
    plan_map = {p.id: p for p in plans}

    # 获取 shipment_records 中的出货汇总
    shipped_result = await db.execute(
        select(
            ShipmentRecord.customer_name,
            ShipmentRecord.product_name,
            func.coalesce(func.sum(ShipmentRecord.quantity), 0).label('total_qty'),
        )
        .where(and_(
            ShipmentRecord.shipment_date >= start,
            ShipmentRecord.shipment_date <= end,
        ))
        .group_by(ShipmentRecord.customer_name, ShipmentRecord.product_name)
    )
    shipped_map = {(r.customer_name, r.product_name): r.total_qty for r in shipped_result.all()}

    for d in details:
        plan = plan_map.get(d.plan_id)
        if not plan:
            continue
        key = (plan.customer_name, d.product_name)
        d.shipped_qty = shipped_map.get(key, 0)


# ==================== 操作日志 ====================

async def _log_action(db: AsyncSession, plan_id: int, action: str,
                      old_value: dict | None, new_value: dict | None,
                      operator: str) -> None:
    """记录操作日志"""
    log = ProductionPlanLog(
        plan_id=plan_id,
        action=action,
        old_value=json.dumps(old_value, ensure_ascii=False) if old_value else None,
        new_value=json.dumps(new_value, ensure_ascii=False) if new_value else None,
        operator=operator,
    )
    db.add(log)
    await db.flush()
