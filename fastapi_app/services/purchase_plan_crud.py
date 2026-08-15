"""
采购计划 CRUD 与业务操作

职责：采购计划的创建、更新、删除、查询、暂存区管理、出货重算等。
FIFO 分配算法已拆分至 fifo_allocation.py。
从 purchase_plan_service.py 拆分而来，保持函数签名不变。
"""
import asyncio
import calendar
import io
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timezone, timedelta

import openpyxl
from sqlalchemy import and_, delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only, selectinload

from fastapi_app.core.cache import cache_result, invalidate_local_cache
from fastapi_app.core.cache_invalidation import InvalidationStrategy, cache_mgr
from fastapi_app.core.redis_wrapper import safe_get, safe_set

from fastapi_app.services import customer_service, product_service
from fastapi_app.services.notification_service import StockEvent, publish_stock_event
from fastapi_app.services.fifo_allocation import (
    _get_shipped_fifo_map,
    _invalidate_fifo_cache,
)
from fastapi_app.services.plan_utils import (
    build_inventory_map,
    calc_shipment_status,
    normalize_plan_date,
)
from fastapi_app.shared_models import (
    Customer,
    Product,
    ProductionPlanLog,
    PurchasePlan,
    PurchasePlanDetail,
    StagingPurchasePlan,
    StockOut,
)

logger = logging.getLogger(__name__)
INVENTORY_CACHE_PREFIX = 'inventory'
INVENTORY_CACHE_TTL = 300
# 出货记录查询回溯月数（S9: 提取为常量便于统一调整）
SHIPMENT_RECORD_LOOKBACK_MONTHS = 12


def _schedule_post_commit(db: AsyncSession, callback: Callable[[], Awaitable[None]]) -> None:
    """注册事务提交成功后执行的异步回调。

    回调会在 db_transaction 上下文管理器成功 commit 后按注册顺序执行；
    若事务回滚则不会执行，避免缓存失效/事件发布发生在持久化失败时。
    """
    callbacks = db.info.setdefault('post_commit_callbacks', [])
    callbacks.append(callback)


async def _invalidate_plan_caches(plan_month: str = '') -> None:
    """清除采购计划相关所有缓存（FIFO + 月度日历 + 客户汇总）

    S4 修复：除了失效 Redis L2 缓存，还显式失效进程内 L1 本地缓存。
    多 worker 部署时 local_ttl 窗口内可能读到陈旧数据，此处统一清除。

    S2 修复：L1 失效模式收窄为精确键 + 前缀通配，避免 `*2026-07*` 误伤无关缓存。
        - FIFO 缓存键固定为 `plan_fifo:YYYY-MM`，用精确匹配。
        - monthly/summary 缓存键以 `pp:monthly:` / `pp:summary:` 为前缀，用前缀通配。
    """
    if plan_month:
        await _invalidate_fifo_cache(plan_month)
        # L1 本地缓存：FIFO 键为 `plan_fifo:YYYY-MM`，精确匹配避免误清
        invalidate_local_cache(f'plan_fifo:{plan_month}')
    await cache_mgr.invalidate(InvalidationStrategy.PATTERN, 'pp:monthly:*')
    await cache_mgr.invalidate(InvalidationStrategy.PATTERN, 'pp:summary:*')
    # L1 本地缓存：pp:monthly 和 pp:summary 都用 cache_result 装饰，键形如 `pp:monthly:...`
    invalidate_local_cache('pp:monthly:*')
    invalidate_local_cache('pp:summary:*')

async def _generate_plan_no() -> str:
    """
    生成计划编号：PP-YYYYMMDD-NNNN

    使用独立短事务执行 pg_advisory_xact_lock + SELECT ... FOR UPDATE，
    查询后立即 commit 释放锁，避免在调用方长事务（含 Redis 缓存失效、
    pub/sub 推送等 I/O）期间持锁导致并发请求串行化。

    事务边界策略与 services.numbering.generate_number_async 一致（短事务 + 立即 commit），
    但未引入 asyncio.Lock 进程内串行化与内存计数器补偿层，并发冲突由 plan_no 唯一约束
    + 调用方 _persist_plan_with_retry 的 3 次重试兜底处理。若未来高并发场景冲突频繁，
    可参考 numbering.py 补充 asyncio.Lock + _counters 内存计数器。

    N2 修复：移除未使用的 db 参数。
    """
    from fastapi_app.core.database import _AsyncSessionLocal
    from fastapi_app.core.number_generator import _acquire_advisory_lock_async, _number_lock_key

    today_str = datetime.now(timezone.utc).strftime('%Y%m%d')
    prefix = f'PP-{today_str}-'
    async with _AsyncSessionLocal() as short_session:
        await _acquire_advisory_lock_async(short_session, _number_lock_key('PP', today_str))
        result = await short_session.execute(
            select(PurchasePlan.plan_no)
            .where(PurchasePlan.plan_no.like(f'{prefix}%'))
            .order_by(PurchasePlan.plan_no.desc())
            .limit(1)
            .with_for_update()
        )
        max_no = result.scalar()
        await short_session.commit()
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

def _validate_plan_month(plan_month: str) -> tuple[int, int]:
    """验证并解析计划月份格式，返回(year, month)"""
    ym_parts = plan_month.split('-')
    if len(ym_parts) != 2:
        raise ValueError(f'月份格式不正确: {plan_month}，请使用 YYYY-MM 格式')
    return int(ym_parts[0]), int(ym_parts[1])


def _validate_details_cross_month(details: list[dict], target_year: int, target_month: int, plan_month: str) -> None:
    """验证明细日期不跨月"""
    for d in details:
        plan_date_val = normalize_plan_date(d['plan_date'])
        if plan_date_val.year != target_year or plan_date_val.month != target_month:
            raise ValueError(f"计划日期 {d['plan_date']} 与计划月份 {plan_month} 不一致，不允许跨月")


async def _validate_products_exist(db: AsyncSession, details: list[dict]) -> None:
    """验证明细中产品（barcode/product_name）均存在"""
    barcodes_to_check = list({d.get('barcode', '') for d in details if d.get('barcode')})
    if barcodes_to_check:
        result = await db.execute(select(Product.barcode).where(Product.barcode.in_(barcodes_to_check)))
        existing = {row[0] for row in result.all()}
        for d in details:
            barcode = d.get('barcode', '')
            if barcode and barcode not in existing:
                raise ValueError(f"69码 '{barcode}' 未找到对应产品")
    names_to_check = list({d.get('product_name', '') for d in details if not d.get('barcode') and d.get('product_name')})
    if names_to_check:
        result = await db.execute(select(Product.name).where(Product.name.in_(names_to_check)))
        existing = {row[0] for row in result.all()}
        for d in details:
            pname = d.get('product_name', '')
            if not d.get('barcode') and pname and pname not in existing:
                raise ValueError(f"产品 '{pname}' 未找到对应记录")


def _format_insufficient_error(insufficient: list[dict]) -> str:
    """格式化库存不足错误信息"""
    parts = []
    for it in insufficient:
        prefix = f"{it['barcode']}(" if it['barcode'] else ''
        suffix = ')' if it['barcode'] else ''
        parts.append(f"产品 {prefix}{it['product_name']}{suffix} 计划数量 {it['total_quantity']}，当前库存 {it['current_stock']}，不足 {it['total_quantity'] - it['current_stock']}")
    return '; '.join(parts)


class PlanExistsError(ValueError):
    """该客户当月已存在采购计划（uq_ppl_month_customer 唯一约束冲突）"""


async def _persist_plan_with_retry(db: AsyncSession, *, customer_id: int, customer_name: str, plan_month: str, remark: str, upload_batch: str, created_by: str) -> PurchasePlan:
    """创建主单记录，含编号冲突重试（最多3次）

    IntegrityError 区分两类冲突：
        - uq_ppl_month_customer：该客户当月已有计划，重试无意义 → 抛 PlanExistsError
        - plan_no 唯一冲突：编号生成竞态 → 重试生成新编号
    """
    for attempt in range(3):
        plan_no = await _generate_plan_no()
        try:
            async with db.begin_nested():
                plan = PurchasePlan(plan_no=plan_no, plan_month=plan_month, customer_id=customer_id, customer_name=customer_name, status='pending', remark=remark, upload_batch=upload_batch, created_by=created_by)
                db.add(plan)
                await db.flush()
            return plan
        except IntegrityError as e:
            err_msg = str(e.orig) if e.orig else str(e)
            # uq_ppl_month_customer 唯一约束：重试新 plan_no 仍会失败，直接终止
            if 'uq_ppl_month_customer' in err_msg or 'purchase_plans_customer_id_plan_month_key' in err_msg:
                raise PlanExistsError(f'该客户当月已存在采购计划：customer_id={customer_id} plan_month={plan_month}') from None
            # plan_no 唯一冲突 → 重试生成新编号
            if attempt == 2:
                raise ValueError('单号生成冲突，请勿重复提交') from None
            logger.warning(f'plan_no {plan_no} 冲突，重试({attempt + 1}/3)')


async def create_plan(db: AsyncSession, *, customer_id: int, customer_name: str, plan_month: str, details: list[dict], remark: str='', created_by: str='', upload_batch: str='') -> dict:
    """
    创建采购计划主单 + 明细

    details 格式: [{'product_id': int, 'product_name': str, 'barcode': str,
                     'quantity': int, 'plan_date': str, 'remark': str}]
    """
    customer = await db.execute(select(Customer).where(Customer.id == customer_id))
    if not customer.scalar_one_or_none():
        raise ValueError(f'客户ID {customer_id} 不存在')
    target_year, target_month = _validate_plan_month(plan_month)
    _validate_details_cross_month(details, target_year, target_month, plan_month)
    await _validate_products_exist(db, details)
    insufficient = await _check_inventory_realtime(db, [{'barcode': d.get('barcode', ''), 'product_name': d.get('product_name', ''), 'quantity': d['quantity']} for d in details], with_for_update=True)
    if insufficient:
        raise ValueError(f'库存不足，无法创建出货计划：{_format_insufficient_error(insufficient)}')
    plan = await _persist_plan_with_retry(db, customer_id=customer_id, customer_name=customer_name, plan_month=plan_month, remark=remark, upload_batch=upload_batch, created_by=created_by)
    for d in details:
        plan_date_val = normalize_plan_date(d['plan_date'])
        detail = PurchasePlanDetail(plan_id=plan.id, product_id=d['product_id'], product_name=d['product_name'], barcode=d['barcode'], plan_date=plan_date_val, quantity=d['quantity'], shipped_qty=0, remark=d.get('remark', ''))
        db.add(detail)
    await _log_action(db, plan.id, 'create', None, plan.to_dict(), created_by)
    await db.flush()

    async def _post_commit():
        await _invalidate_plan_caches(plan_month)
        await publish_stock_event(StockEvent.SHIPMENT_PLAN_UPLOADED, {'plan_id': plan.id, 'plan_no': plan.plan_no, 'customer_name': customer_name, 'detail_count': len(details)})
    _schedule_post_commit(db, _post_commit)

    logger.info(f'采购计划创建成功：{plan.plan_no} - {customer_name} - {len(details)}条明细')
    return {'plan_id': plan.id, 'plan_no': plan.plan_no}

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
    await db.flush()

    async def _post_commit():
        await _invalidate_plan_caches(plan.plan_month)
        await publish_stock_event(StockEvent.SHIPMENT_PLAN_UPLOADED, {'plan_id': plan.id, 'operation': 'update'})
    _schedule_post_commit(db, _post_commit)

    return plan.to_dict()

async def delete_plan(db: AsyncSession, plan_id: int, *, operator: str='') -> None:
    """删除采购计划主单及明细"""
    result = await db.execute(select(PurchasePlan).where(PurchasePlan.id == plan_id))
    plan = result.scalar_one_or_none()
    if not plan:
        raise ValueError('采购计划不存在')
    old_data = plan.to_dict()
    plan_month = plan.plan_month
    await db.delete(plan)
    await _log_action(db, plan.id, 'delete', old_data, None, operator)
    await db.flush()

    async def _post_commit():
        await _invalidate_plan_caches(plan_month)
        await publish_stock_event(StockEvent.STOCK_CHANGED, {'plan_id': plan_id, 'operation': 'delete', 'customer_name': old_data.get('customer_name', '')})
    _schedule_post_commit(db, _post_commit)

    logger.info(f'采购计划删除成功：ID={plan_id}')

async def update_detail(db: AsyncSession, detail_id: int, *, created_by: str='', **kwargs) -> dict:
    """更新单条明细

    B3 修复：当 quantity 增加时，重新校验库存防止超额计划。
    """
    result = await db.execute(select(PurchasePlanDetail).where(PurchasePlanDetail.id == detail_id))
    detail = result.scalar_one_or_none()
    if not detail:
        raise ValueError('明细记录不存在')
    # 获取 plan_month 用于缓存清除
    plan_result = await db.execute(select(PurchasePlan.plan_month).where(PurchasePlan.id == detail.plan_id))
    plan_month_row = plan_result.first()

    # B3: 数量增加时校验库存（按增量需求）
    new_quantity = kwargs.get('quantity')
    if new_quantity is not None and new_quantity > detail.quantity:
        increment = new_quantity - detail.quantity
        check_items = [{'barcode': detail.barcode, 'product_name': detail.product_name, 'quantity': increment}]
        insufficient = await _check_inventory_realtime(db, check_items, with_for_update=True)
        if insufficient:
            raise ValueError(f'库存不足，无法增加数量：{_format_insufficient_error(insufficient)}')

    for field in ('quantity', 'plan_date', 'remark'):
        if field in kwargs and kwargs[field] is not None:
            if field == 'plan_date':
                detail.plan_date = normalize_plan_date(kwargs[field])
            else:
                setattr(detail, field, kwargs[field])
    await db.flush()

    async def _post_commit():
        if plan_month_row:
            await _invalidate_plan_caches(plan_month_row[0])
        await publish_stock_event(StockEvent.SHIPMENT_PLAN_UPLOADED, {'detail_id': detail_id, 'operation': 'update_detail'})
    _schedule_post_commit(db, _post_commit)

    return detail.to_dict()

async def delete_detail(db: AsyncSession, detail_id: int) -> None:
    """删除单条明细"""
    result = await db.execute(select(PurchasePlanDetail).where(PurchasePlanDetail.id == detail_id))
    detail = result.scalar_one_or_none()
    if not detail:
        raise ValueError('明细记录不存在')
    plan_result = await db.execute(select(PurchasePlan.plan_month).where(PurchasePlan.id == detail.plan_id))
    plan_month_row = plan_result.first()
    await db.delete(detail)
    await db.flush()

    async def _post_commit():
        if plan_month_row:
            await _invalidate_plan_caches(plan_month_row[0])
        await publish_stock_event(StockEvent.STOCK_CHANGED, {'detail_id': detail_id, 'operation': 'delete_detail'})
    _schedule_post_commit(db, _post_commit)

async def add_details(db: AsyncSession, plan_id: int, details: list[dict]) -> dict:
    """向主单追加明细

    B3 修复：追加明细前必须校验库存，与 create_plan 行为一致。
    """
    result = await db.execute(select(PurchasePlan).where(PurchasePlan.id == plan_id))
    plan = result.scalar_one_or_none()
    if not plan:
        raise ValueError('采购计划不存在')
    ym_parts = plan.plan_month.split('-')
    target_year, target_month = (int(ym_parts[0]), int(ym_parts[1]))
    # B3: 校验产品存在 + 库存（与 create_plan 一致）
    await _validate_products_exist(db, details)
    insufficient = await _check_inventory_realtime(db, [{'barcode': d.get('barcode', ''), 'product_name': d.get('product_name', ''), 'quantity': d['quantity']} for d in details], with_for_update=True)
    if insufficient:
        raise ValueError(f'库存不足，无法追加明细：{_format_insufficient_error(insufficient)}')
    added = 0
    for d in details:
        plan_date_val = normalize_plan_date(d['plan_date'])
        if plan_date_val.year != target_year or plan_date_val.month != target_month:
            raise ValueError(f"计划日期 {d['plan_date']} 与主单月份 {plan.plan_month} 不一致")
        detail = PurchasePlanDetail(plan_id=plan_id, product_id=d['product_id'], product_name=d['product_name'], barcode=d['barcode'], plan_date=plan_date_val, quantity=d['quantity'], shipped_qty=0, remark=d.get('remark', ''))
        db.add(detail)
        added += 1
    await db.flush()

    async def _post_commit():
        await _invalidate_plan_caches(plan.plan_month)
    _schedule_post_commit(db, _post_commit)

    return {'added_count': added}

async def _get_inventory_map(db: AsyncSession) -> dict:
    """
    获取库存查找字典 key=(customer_name, product_name) value=total_stock
    优先从 Redis 缓存读取，缓存未命中则查询 stock_service
    超时保护：asyncio.timeout(8) 防止 _fetch_inventory 的4条聚合SQL长时间阻塞
    """
    cached = await safe_get(f'{INVENTORY_CACHE_PREFIX}:map', context='库存映射缓存')
    if cached is not None:
        return {tuple(k.split('||')): v for k, v in cached.items()}
    try:
        async with asyncio.timeout(8):
            from fastapi_app.services import stock_service
            inventory_result = await stock_service.get_inventory(db)
        mapping = build_inventory_map(inventory_result['inventory_data'])
    except asyncio.TimeoutError:
        logger.error('库存查询超时(8s)，返回空映射降级')
        return {}
    except (ValueError, TypeError, OSError) as e:
        logger.warning(f'获取库存数据失败: {e}')
        return {}
    cacheable = {f'{k[0]}||{k[1]}': v for k, v in mapping.items()}
    await safe_set(f'{INVENTORY_CACHE_PREFIX}:map', cacheable, timeout=INVENTORY_CACHE_TTL, context='库存映射缓存')
    return mapping

def _calc_stock_status(plan_qty: int, inventory_qty: int) -> str:
    """库存状态：充足(>=计划) / 紧张(0<库存<计划) / 无库存(库存=0)"""
    if inventory_qty <= 0:
        return 'no_stock'
    elif inventory_qty >= plan_qty:
        return 'sufficient'
    return 'shortage'

async def _fetch_barcode_stock(db: AsyncSession, barcode_items: list[dict], *, with_for_update: bool=False) -> dict[str, dict]:
    """通过 barcode 查询库存, 返回 {barcode: {'name': str, 'current_stock': int}}

    B1 修复：with_for_update=True 时附加 SELECT ... FOR UPDATE 行级锁，
    防止 TOCTOU 竞态（校验通过后并发请求仍能修改库存）。
    """
    if not barcode_items:
        return {}
    barcodes = list({item['barcode'] for item in barcode_items})
    stmt = select(Product.id, Product.barcode, Product.name, Product.current_stock).where(Product.barcode.in_(barcodes))
    if with_for_update:
        stmt = stmt.with_for_update()
    result = await db.execute(stmt)
    return {row.barcode: {'name': row.name, 'current_stock': row.current_stock or 0} for row in result.all()}


async def _fetch_name_stock(db: AsyncSession, name_items: list[dict], *, with_for_update: bool=False) -> dict[str, dict]:
    """通过 product_name 查询库存(barcode 为空时), 返回 {name: {'current_stock': int}}

    B1 修复：with_for_update=True 时附加 SELECT ... FOR UPDATE 行级锁。
    """
    if not name_items:
        return {}
    names = list({item['product_name'] for item in name_items if item.get('product_name')})
    if not names:
        return {}
    stmt = select(Product.id, Product.name, Product.current_stock).where(Product.name.in_(names))
    if with_for_update:
        stmt = stmt.with_for_update()
    result = await db.execute(stmt)
    return {row.name: {'current_stock': row.current_stock or 0} for row in result.all()}


def _aggregate_barcode_demand(barcode_items: list[dict], product_stock_map: dict[str, dict]) -> dict[str, dict]:
    """按 barcode 汇总需求量"""
    demand_map: dict[str, dict] = {}
    for item in barcode_items:
        barcode = item['barcode']
        if barcode not in demand_map:
            info = product_stock_map.get(barcode)
            demand_map[barcode] = {'product_name': item.get('product_name', '') or (info['name'] if info else ''), 'total_quantity': 0, 'current_stock': info['current_stock'] if info else 0}
        demand_map[barcode]['total_quantity'] += item['quantity']
    return demand_map


def _aggregate_name_demand(name_items: list[dict], name_stock_map: dict[str, dict]) -> dict[str, dict]:
    """按 product_name 汇总无 barcode 的项"""
    name_demand_map: dict[str, dict] = {}
    for item in name_items:
        pname = item.get('product_name', '')
        if not pname:
            continue
        if pname not in name_demand_map:
            info = name_stock_map.get(pname)
            name_demand_map[pname] = {'product_name': pname, 'total_quantity': 0, 'current_stock': info['current_stock'] if info else 0}
        name_demand_map[pname]['total_quantity'] += item['quantity']
    return name_demand_map


def _collect_insufficient(demand_map: dict[str, dict], name_demand_map: dict[str, dict]) -> list[dict]:
    """收集库存不足项"""
    insufficient = []
    for barcode, demand in demand_map.items():
        if demand['current_stock'] < demand['total_quantity']:
            insufficient.append({'barcode': barcode, 'product_name': demand['product_name'], 'total_quantity': demand['total_quantity'], 'current_stock': demand['current_stock']})
    for pname, demand in name_demand_map.items():
        if demand['current_stock'] < demand['total_quantity']:
            insufficient.append({'barcode': '', 'product_name': pname, 'total_quantity': demand['total_quantity'], 'current_stock': demand['current_stock']})
    return insufficient


async def _check_inventory_realtime(db: AsyncSession, items: list[dict], *, with_for_update: bool=False) -> list[dict]:
    """
    实时库存校验（直接查数据库，不经过缓存）
    同一 barcode 多条记录会汇总需求量后与库存比较
    无 barcode 时按 product_name 匹配

    参数:
        items: [{'barcode': str, 'product_name': str, 'quantity': int}, ...]
        with_for_update: True 时附加 SELECT ... FOR UPDATE 行级锁，防止
                         TOCTOU 竞态（写入路径 create_plan/add_details/update_detail/
                         confirm_staging 必须传 True）。读取路径（validate_staging
                         仅作提示）可传 False。
    返回:
        库存不足项列表 [{'barcode': str, 'product_name': str, 'total_quantity': int, 'current_stock': int}, ...]
    """
    if not items:
        return []

    barcode_items = [item for item in items if item.get('barcode')]
    name_items = [item for item in items if not item.get('barcode')]

    product_stock_map = await _fetch_barcode_stock(db, barcode_items, with_for_update=with_for_update)
    name_stock_map = await _fetch_name_stock(db, name_items, with_for_update=with_for_update)

    demand_map = _aggregate_barcode_demand(barcode_items, product_stock_map)
    name_demand_map = _aggregate_name_demand(name_items, name_stock_map)

    return _collect_insufficient(demand_map, name_demand_map)

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
    date_limit = _compute_shipment_lookback_limit(plan.plan_month)
    result = await db.execute(select(StockOut.id, StockOut.stockout_no, StockOut.stockout_date, StockOut.quantity, StockOut.returned_quantity, StockOut.customer, StockOut.note, Product.name.label('product_name')).join(Product, StockOut.product_id == Product.id).where(and_(StockOut.customer == plan.customer_name, Product.name.in_(product_names), StockOut.customer.isnot(None), StockOut.customer != '', StockOut.stockout_date >= date_limit)).order_by(StockOut.stockout_date.desc(), StockOut.id.desc()).limit(500))
    rows = result.all()
    return [{'stockout_id': row.id, 'shipment_no': row.stockout_no, 'customer_name': row.customer or '', 'product_name': row.product_name, 'quantity': row.quantity - row.returned_quantity, 'shipment_date': row.stockout_date.strftime('%Y-%m-%d') if row.stockout_date else '', 'source_type': 'stockout', 'note': row.note or ''} for row in rows]


def _compute_shipment_lookback_limit(plan_month: str) -> datetime:
    """根据计划月份计算出货记录查询的时间下限（S9 提取的辅助函数）

    返回 datetime 类型，确保与 StockOut.stockout_date(DateTime) 比较时索引可用。
    """
    year, month = map(int, plan_month.split('-'))
    plan_month_start = date(year, month, 1)
    lookback_year = plan_month_start.year - (SHIPMENT_RECORD_LOOKBACK_MONTHS // 12)
    date_limit_date = plan_month_start.replace(year=lookback_year)
    return datetime(date_limit_date.year, date_limit_date.month, date_limit_date.day)


async def get_shipment_records_by_date(db: AsyncSession, target_date: str) -> list[dict]:
    """S1 批量端点：按日期查询所有相关出货流水记录

    用于替代 ShipmentRecordsTab.vue 中按 plan_id 分块 N+1 请求的模式。
    流程：
        1. 根据 target_date 从 monthly_calendar 数据中找出当日所有 plan_ids
        2. 查询这些计划对应的客户名 + 产品名集合
        3. 单次 JOIN 查询 stock_out 返回所有匹配记录
        4. 客户端按 shipment_no 去重

    Args:
        target_date: 'YYYY-MM-DD' 格式日期字符串
    Returns:
        去重后的出货流水列表
    """
    try:
        target_dt = datetime.strptime(target_date, '%Y-%m-%d')
    except ValueError as e:
        raise ValueError(f'日期格式错误: {target_date}，需 YYYY-MM-DD') from e
    plan_month = f'{target_dt.year}-{target_dt.month:02d}'
    # 查询该日所有计划明细对应的客户和产品
    sql = text("""
        SELECT DISTINCT p.customer_name, d.product_name, p.plan_month
        FROM purchase_plan_details d
        JOIN purchase_plans p ON d.plan_id = p.id
        WHERE d.plan_date = :target_date
    """)
    result = await db.execute(sql, {'target_date': target_dt.date()})
    rows = result.all()
    if not rows:
        return []
    # 按客户分组，收集所有产品名
    customers = list({r.customer_name for r in rows if r.customer_name})
    product_names = list({r.product_name for r in rows if r.product_name})
    if not customers or not product_names:
        return []
    # 取最早的 plan_month 计算 date_limit
    earliest_plan_month = min(r.plan_month for r in rows if r.plan_month)
    date_limit = _compute_shipment_lookback_limit(earliest_plan_month)
    # 单次 JOIN 查询所有相关出货记录
    stockout_result = await db.execute(
        select(StockOut.id, StockOut.stockout_no, StockOut.stockout_date, StockOut.quantity, StockOut.returned_quantity, StockOut.customer, StockOut.note, Product.name.label('product_name'))
        .join(Product, StockOut.product_id == Product.id)
        .where(and_(
            StockOut.customer.in_(customers),
            Product.name.in_(product_names),
            StockOut.customer.isnot(None),
            StockOut.customer != '',
            StockOut.stockout_date >= date_limit,
        ))
        .order_by(StockOut.stockout_date.desc(), StockOut.id.desc())
        .limit(500)
    )
    seen = set()
    out: list[dict] = []
    for row in stockout_result.all():
        if row.stockout_no and row.stockout_no in seen:
            continue
        seen.add(row.stockout_no)
        out.append({
            'stockout_id': row.id,
            'shipment_no': row.stockout_no,
            'customer_name': row.customer or '',
            'product_name': row.product_name,
            'quantity': row.quantity - row.returned_quantity,
            'shipment_date': row.stockout_date.strftime('%Y-%m-%d') if row.stockout_date else '',
            'source_type': 'stockout',
            'note': row.note or '',
        })
    return out

@cache_result(
    key_prefix="pp:monthly",
    ttl=120,
    local_ttl=30,
    key_builder=lambda **kwargs: f"v2:y{kwargs.get('year', 0)}:m{kwargs.get('month', 0)}:c{kwargs.get('customer_id', 0)}",
)
async def get_monthly_calendar(db: AsyncSession, year: int, month: int, customer_id: int=0) -> dict:
    """
    月度日历数据：按日期聚合计划，供前端时序面板渲染

    优化项：
    - 移除 _get_inventory_map 调用（前端 PurchasePlanView 不使用 inventory_qty / stock_status）
    - 精简返回字段，减少 JSON 序列化体积
    - shipped_qty 使用 FIFO 实时分配（与其他端点一致，不再依赖过时的 shipped_qty 缓存字段）

    返回:
      plans_by_date: {"2026-04-01": [{...}, ...], ...}
      customers: [{id, name, icon_url}, ...]
    """
    plan_month = f'{year}-{month:02d}'
    days_in_month = calendar.monthrange(year, month)[1]

    # 单条 raw SQL JOIN，跳过 ORM 对象实例化开销
    sql = text("""
        SELECT d.id AS detail_id, d.plan_id, p.customer_id, p.customer_name,
               d.product_name, d.barcode, d.plan_date, d.quantity
        FROM purchase_plan_details d
        JOIN purchase_plans p ON d.plan_id = p.id
        WHERE p.plan_month = :plan_month
    """ + (" AND p.customer_id = :customer_id" if customer_id else ""))

    params: dict = {'plan_month': plan_month}
    if customer_id:
        params['customer_id'] = customer_id

    result = await db.execute(sql, params)
    rows = result.all()

    detail_shipped_map: dict[int, int] = {}
    if rows:
        detail_ids = list({row.detail_id for row in rows})
        detail_result = await db.execute(
            select(PurchasePlanDetail)
            .options(load_only(
                PurchasePlanDetail.id, PurchasePlanDetail.plan_id,
                PurchasePlanDetail.product_name, PurchasePlanDetail.product_id,
                PurchasePlanDetail.plan_date, PurchasePlanDetail.quantity,
            ))
            .where(PurchasePlanDetail.id.in_(detail_ids))
            .order_by(PurchasePlanDetail.plan_date, PurchasePlanDetail.id)
        )
        all_details = detail_result.scalars().all()
        customer_name_map = {}
        for row in rows:
            if row.plan_id not in customer_name_map:
                customer_name_map[row.plan_id] = row.customer_name
        shipped_fifo_map = await _get_shipped_fifo_map(db, all_details, customer_name_map, plan_month=plan_month)
        detail_shipped_map = {d.id: shipped_fifo_map.get(d.id, 0) for d in all_details}

    plans_by_date: dict[str, list[dict]] = {}
    customer_set: dict[int, dict] = {}
    for day in range(1, days_in_month + 1):
        plans_by_date[date(year, month, day).isoformat()] = []

    for row in rows:
        date_str = row.plan_date.isoformat() if row.plan_date else ''
        shp_qty = detail_shipped_map.get(row.detail_id, 0)
        if date_str in plans_by_date:
            plans_by_date[date_str].append({
                'detail_id': row.detail_id,
                'plan_id': row.plan_id,
                'customer_name': row.customer_name,
                'product_name': row.product_name,
                'barcode': row.barcode,
                'quantity': row.quantity,
                'shipped_qty': shp_qty,
                'remaining_qty': row.quantity - shp_qty,
                'plan_date': date_str,
            })
        if row.customer_id not in customer_set:
            customer_set[row.customer_id] = {'id': row.customer_id, 'name': row.customer_name, 'icon_url': None}

    return {'year': year, 'month': month, 'days_in_month': days_in_month, 'plans_by_date': plans_by_date, 'customers': await _enrich_customer_icon_urls(db, list(customer_set.values()))}


async def _enrich_customer_icon_urls(db: AsyncSession, customers: list[dict]) -> list[dict]:
    """S2: 批量查询客户图标URL并填充到 customers 列表

    将原 endpoint 层的二次查询下沉到 service 层，保持端点职责单一。
    """
    if not customers:
        return customers
    customer_ids = [c['id'] for c in customers if c.get('id')]
    if not customer_ids:
        return customers
    c_result = await db.execute(select(Customer).where(Customer.id.in_(customer_ids)))
    c_map = {c.id: c for c in c_result.scalars().all()}
    for c in customers:
        c_obj = c_map.get(c.get('id'))
        if c_obj:
            c['icon_url'] = c_obj.icon_url or ''
    return customers

@cache_result(
    key_prefix="pp:summary",
    ttl=1800,
    local_ttl=5,
    key_builder=lambda **kwargs: f"v2:y{kwargs.get('year', 0)}:m{kwargs.get('month', 0)}",
)
async def get_customer_summary(db: AsyncSession, year: int, month: int) -> dict:
    """客户维度汇总统计，单次 eager loading 查询"""
    plan_month = f'{year}-{month:02d}'
    result = await db.execute(select(PurchasePlan).options(selectinload(PurchasePlan.details)).where(PurchasePlan.plan_month == plan_month))
    plans = result.scalars().all()
    inventory_map = await _get_inventory_map(db)
    # FIFO 分配出货数量
    all_details = [d for plan in plans for d in plan.details]
    customer_name_map = {plan.id: plan.customer_name for plan in plans}
    shipped_fifo_map = await _get_shipped_fifo_map(db, all_details, customer_name_map, plan_month=plan_month)
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
    for ps in product_summary.values():
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

def _load_excel_rows(file_content: bytes) -> list[tuple]:
    """加载 Excel 文件并返回数据行(跳过表头)"""
    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_content), read_only=True)
    except (OSError, ValueError) as e:
        raise ValueError(f'Excel文件解析失败: {e}') from e
    try:
        ws = wb.active
        rows = list(ws.iter_rows(min_row=2, values_only=True))
    finally:
        wb.close()
    return rows


def _parse_excel_row(row: tuple, row_idx: int) -> tuple[dict, str]:
    """解析单行 Excel 数据, 返回 (字段字典, 错误信息)

    S10 修复：Excel 单元格可能为字符串 '10' 或浮点 10.5，
    int(row[3]) 会抛 ValueError；int(float(...)) 兼容两种格式。
    """
    try:
        customer_name = str(row[0] or '').strip()
        product_name = str(row[1] or '').strip()
        barcode = str(row[2] or '').strip()
        # S10: 兼容字符串数字与浮点数；负数/0 在 _validate_excel_row 中拦截
        quantity = int(float(row[3])) if row[3] not in (None, '') else 0
        plan_date_str = str(row[4] or '').strip()
        remark = str(row[5] or '').strip() if len(row) > 5 and row[5] else ''
        return {'customer_name': customer_name, 'product_name': product_name, 'barcode': barcode, 'quantity': quantity, 'plan_date_str': plan_date_str, 'remark': remark}, ''
    except (ValueError, IndexError) as e:
        return {}, f'第{row_idx}行: 数据格式错误 - {e}'


def _validate_excel_row(fields: dict, detected_month: str | None) -> tuple[str, str | None]:
    """校验行字段, 返回 (validation_error, new_detected_month)"""
    if not fields['customer_name']:
        return '客户名称为空', None
    if not fields['barcode']:
        return '69码为空', None
    if fields['quantity'] <= 0:
        return '数量必须为正整数', None
    if not fields['plan_date_str']:
        return '计划日期为空', None
    try:
        parsed_date = normalize_plan_date(fields['plan_date_str'])
        row_month = f'{parsed_date.year}-{parsed_date.month:02d}'
        if detected_month is None:
            return '', row_month
        if row_month != detected_month:
            return f'日期月份 {row_month} 与之前行月份 {detected_month} 不一致，不允许跨月', None
        return '', None
    except ValueError as e:
        return str(e), None


async def upload_excel(db: AsyncSession, file_content: bytes, session_id: str, created_by: str='') -> dict:
    """解析Excel文件，写入暂存表，返回预览数据"""
    batch_id = str(uuid.uuid4())[:8]
    rows = _load_excel_rows(file_content)
    if not rows:
        raise ValueError('Excel文件无数据行')
    detected_month = None
    staging_records = []
    errors = []
    success_count = 0
    for i, row in enumerate(rows, start=2):
        if not row or all(c is None for c in row):
            continue
        fields, parse_error = _parse_excel_row(row, i)
        if parse_error:
            errors.append(parse_error)
            continue
        validation_error, new_month = _validate_excel_row(fields, detected_month)
        if new_month:
            detected_month = new_month
        record = StagingPurchasePlan(session_id=session_id, customer_name=fields['customer_name'], product_name=fields['product_name'], barcode=fields['barcode'], quantity=fields['quantity'], plan_date=normalize_plan_date(fields['plan_date_str']) if not validation_error else date.today(), plan_month=detected_month, remark=fields['remark'], is_validated=0, validation_error=validation_error, upload_batch_id=batch_id)
        db.add(record)
        staging_records.append(record)
        if not validation_error:
            success_count += 1
    await db.flush()
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
    barcode_map = await product_service.get_product_barcode_map(db)
    barcode_set = set(barcode_map.keys())
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
        elif not record.product_name and record.barcode in barcode_map:
            record.product_name = barcode_map[record.barcode]
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
    return {'total': len(records), 'valid_count': valid_count, 'error_count': error_count}

def _group_staging_records(valid_records: list) -> dict[tuple[str, str], list]:
    """按 (customer_name, plan_month) 分组"""
    groups: dict[tuple[str, str], list] = {}
    for record in valid_records:
        key = (record.customer_name, record.plan_month or '')
        groups.setdefault(key, []).append(record)
    return groups


async def _get_or_create_plan_for_group(
    db: AsyncSession,
    customer_id: int,
    customer_name: str,
    plan_month: str,
    batch_id: str,
    created_by: str,
) -> PurchasePlan:
    """获取或创建指定客户+月份的采购计划主单

    B2 修复：
        1. SELECT 时附加 with_for_update() 行级锁，防止并发 confirm_staging
           双双通过 "不存在" 检查后各自创建主单。
        2. 数据库侧新增 UNIQUE(customer_id, plan_month) 索引（migration
           pg_standalone_018），作为最后防线；并发 INSERT 触发 IntegrityError
           时重试 SELECT 读取已创建的主单。
    N3 修复：删除循环末尾不可达的 raise。
    """
    # with_for_update 锁住已存在行；若不存在则不锁任何行，依赖唯一索引兜底
    existing = await db.execute(
        select(PurchasePlan)
        .where(and_(PurchasePlan.customer_id == customer_id, PurchasePlan.plan_month == plan_month))
        .with_for_update()
    )
    existing_plan = existing.scalar_one_or_none()
    if existing_plan:
        return existing_plan
    for _attempt in range(3):
        plan_no = await _generate_plan_no()
        try:
            async with db.begin_nested():
                plan = PurchasePlan(plan_no=plan_no, plan_month=plan_month, customer_id=customer_id, customer_name=customer_name, status='pending', upload_batch=batch_id, created_by=created_by)
                db.add(plan)
                await db.flush()
            return plan
        except IntegrityError as e:
            err_msg = str(e.orig) if e.orig else str(e)
            # uq_ppl_month_customer: 并发 confirm_staging 已创建相同 (customer_id, plan_month) 主单
            # → 重试 SELECT 读取已存在的主单，避免重复创建
            if 'uq_ppl_month_customer' in err_msg or 'purchase_plans_customer_id_plan_month_key' in err_msg:
                re_fetch = await db.execute(
                    select(PurchasePlan)
                    .where(and_(PurchasePlan.customer_id == customer_id, PurchasePlan.plan_month == plan_month))
                )
                re_plan = re_fetch.scalar_one_or_none()
                if re_plan:
                    logger.info(f'_get_or_create_plan_for_group: 并发冲突，重用已存在主单 customer_id={customer_id} plan_month={plan_month}')
                    return re_plan
                # 极端情况：唯一索引未创建但 plan_no 冲突 → 走原重试逻辑
            # plan_no 唯一约束冲突 → 重试生成新编号
            if _attempt == 2:
                raise ValueError('单号生成冲突，请勿重复提交') from None
            logger.warning(f'confirm_staging: plan_no {plan_no} 冲突，重试({_attempt + 1}/3)')


def _create_details_for_group(
    db: AsyncSession,
    plan: PurchasePlan,
    group_records: list,
    barcode_to_product: dict,
) -> int:
    """为分组创建明细, 返回创建数量"""
    created = 0
    for record in group_records:
        product = barcode_to_product.get(record.barcode)
        detail = PurchasePlanDetail(plan_id=plan.id, product_id=product.id if product else 0, product_name=record.product_name, barcode=record.barcode, plan_date=record.plan_date, quantity=record.quantity, shipped_qty=0, remark=record.remark or '')
        db.add(detail)
        created += 1
    return created


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
    insufficient = await _check_inventory_realtime(db, [{'barcode': r.barcode, 'product_name': r.product_name, 'quantity': r.quantity} for r in valid_records], with_for_update=True)
    if insufficient:
        errors = '; '.join(f"产品 {it['barcode']}({it['product_name']}) 当前库存 {it['current_stock']} 库存不足 {it['total_quantity'] - it['current_stock']}" for it in insufficient)
        raise ValueError(f'库存不足，无法确认：{errors}')
    groups = _group_staging_records(valid_records)
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
        plan = await _get_or_create_plan_for_group(db, customer_id, customer_name, plan_month, batch_id, created_by)
        created_details += _create_details_for_group(db, plan, group_records, barcode_to_product)
        created_plans.append({'plan_id': plan.id, 'plan_no': plan.plan_no})
    await db.execute(delete(StagingPurchasePlan).where(*conditions))
    await db.flush()
    # 清除所有涉及月份的缓存（confirm_staging 可能跨多月），延迟到事务提交成功后执行
    affected_months = {pm for _, pm in groups.keys() if pm}

    async def _post_commit():
        for pm in affected_months:
            await _invalidate_plan_caches(pm)
    _schedule_post_commit(db, _post_commit)

    logger.info(f'暂存数据确认保存：{len(created_plans)}个主单，{created_details}条明细')
    return {'created_plans': created_plans, 'created_count': created_details, 'skipped_count': len(records) - len(valid_records)}

async def clear_staging(db: AsyncSession, session_id: str) -> None:
    """清空暂存区"""
    await db.execute(delete(StagingPurchasePlan).where(StagingPurchasePlan.session_id == session_id))
    await db.flush()

async def validate_barcode(db: AsyncSession, barcode: str) -> dict:
    """验证69码，返回关联的产品信息"""
    result = await db.execute(select(Product).where(Product.barcode == barcode))
    product = result.scalar_one_or_none()
    if not product:
        return {'valid': False, 'product_name': None, 'message': f"69码 '{barcode}' 未找到对应产品"}
    return {'valid': True, 'product_name': product.name, 'product_id': product.id, 'message': '验证通过'}

# S5: 已移除 deprecated sync_shipment_records 和 _refresh_shipped_qty
# 这两个函数依赖已废弃的 ShipmentRecord 表，所有读路径已改用 FIFO 实时查询。
# 若需保留同步功能，请使用新的 FIFO 缓存失效机制：_invalidate_plan_caches(plan_month)。

async def _log_action(db: AsyncSession, plan_id: int, action: str, old_value: dict | None, new_value: dict | None, operator: str) -> None:
    """记录操作日志"""
    log = ProductionPlanLog(plan_id=plan_id, action=action, old_value=json.dumps(old_value, ensure_ascii=False) if old_value else None, new_value=json.dumps(new_value, ensure_ascii=False) if new_value else None, operator=operator)
    db.add(log)
    await db.flush()


def _recalc_plan_status(details: list[PurchasePlanDetail], shipped_map: dict[int, int], current_status: str = 'confirmed') -> str:
    """根据明细出货情况推算计划状态：全部完成→completed，否则 confirmed。pending/cancelled 保持不变"""
    if current_status in ('pending', 'cancelled'):
        return current_status
    if not details:
        return 'confirmed'
    for d in details:
        if shipped_map.get(d.id, 0) < d.quantity:
            return 'confirmed'
    return 'completed'


async def _fetch_affected_plans_and_details(
    db: AsyncSession,
    customer_name: str,
    product_name: str,
) -> tuple[list, list, list]:
    """查询受影响的计划、明细和相关明细"""
    plan_result = await db.execute(
        select(PurchasePlan).where(PurchasePlan.customer_name == customer_name)
    )
    affected_plans = plan_result.scalars().all()
    if not affected_plans:
        return [], [], []

    affected_plan_ids = [p.id for p in affected_plans]
    detail_result = await db.execute(
        select(PurchasePlanDetail)
        .where(PurchasePlanDetail.plan_id.in_(affected_plan_ids))
        .order_by(PurchasePlanDetail.plan_date, PurchasePlanDetail.id)
        .with_for_update()
    )
    all_affected_details = detail_result.scalars().all()
    related_details = [d for d in all_affected_details if d.product_name == product_name]
    return affected_plans, all_affected_details, related_details


async def _update_shipped_qty(
    db: AsyncSession,
    related_details: list,
    affected_plans: list,
) -> None:
    """重新 FIFO 分配并更新 shipped_qty"""
    customer_name_map = {p.id: p.customer_name for p in affected_plans}
    shipped_fifo_map = await _get_shipped_fifo_map(db, related_details, customer_name_map)
    for detail in related_details:
        detail.shipped_qty = shipped_fifo_map.get(detail.id, 0)
    await db.flush()


def _recalc_plan_statuses(
    affected_plans: list,
    all_affected_details: list,
    product_name: str,
) -> dict[int, dict]:
    """重新计算受影响计划的状态, 返回状态变更字典"""
    details_by_plan: dict[int, list[PurchasePlanDetail]] = {}
    for detail in all_affected_details:
        details_by_plan.setdefault(detail.plan_id, []).append(detail)

    status_changes: dict[int, dict] = {}
    for plan in affected_plans:
        plan_details = details_by_plan.get(plan.id, [])
        has_related = any(detail.product_name == product_name for detail in plan_details)
        if not has_related:
            continue
        old_status = plan.status
        shipped_map = {detail.id: detail.shipped_qty for detail in plan_details}
        new_status = _recalc_plan_status(plan_details, shipped_map, current_status=old_status)
        if old_status != new_status:
            plan.status = new_status
            status_changes[plan.id] = {'old_status': old_status, 'new_status': new_status}
    return status_changes


def _build_recalc_log_values(
    action_type: str,
    snapshot_before: dict[int, dict] | None,
    extra_old_value: dict | None,
    product_name: str,
    plan_id: int,
    plan_related: list,
    status_changes: dict[int, dict],
    plan_details_snap: list,
) -> tuple[dict, dict]:
    """构建重算日志的 old_value 和 new_value"""
    if action_type == 'rollback_stockout' and snapshot_before:
        old_value = {'product_name': product_name, **(extra_old_value or {})}
        old_value['details_before'] = [snapshot_before[d.id] for d in plan_related]
        old_value['status_change'] = status_changes.get(plan_id)
        new_value = {
            'details_after': plan_details_snap,
            'status_change': status_changes.get(plan_id),
        }
    else:
        old_value = {'product_name': product_name}
        new_value = {'details': plan_details_snap, 'status_change': status_changes.get(plan_id)}
    return old_value, new_value


async def _recalc_plans_common(
    db: AsyncSession,
    customer_name: str,
    product_name: str,
    action_type: str,
    *,
    operator: str = '',
    snapshot_before: dict[int, dict] | None = None,
    extra_old_value: dict | None = None,
    prefetched: tuple[list, list, list] | None = None,
) -> tuple[dict[int, dict], int]:
    """
    采购计划重算的公共逻辑（出货记录创建/删除后重新计算 shipped_qty 和状态）

    参数:
        db: 数据库会话
        customer_name: 客户名称
        product_name: 产品名称
        action_type: 操作类型 ('recalc_stockout' 或 'rollback_stockout')
        operator: 操作者
        snapshot_before: 回滚前的快照（仅用于 rollback_stockout）
        extra_old_value: 追加到日志 old_value 的额外字段（如 stockout_no、quantity）
        prefetched: 预查询数据 (affected_plans, all_affected_details, related_details)，
                    传入时跳过内部查询以避免重复 DB 访问

    返回:
        (状态变更字典, 受影响计划数)
    """
    if not customer_name or not product_name:
        return {}, 0

    if prefetched is not None:
        affected_plans, all_affected_details, related_details = prefetched
    else:
        affected_plans, all_affected_details, related_details = await _fetch_affected_plans_and_details(db, customer_name, product_name)

    if not affected_plans or not related_details:
        return {}, len(affected_plans)

    affected_plan_ids = [p.id for p in affected_plans]

    await _update_shipped_qty(db, related_details, affected_plans)

    status_changes = _recalc_plan_statuses(affected_plans, all_affected_details, product_name)
    await db.flush()

    # 6. 记录操作日志(预分组避免嵌套循环)
    related_by_plan: dict[int, list] = {}
    for detail in related_details:
        related_by_plan.setdefault(detail.plan_id, []).append(detail)

    for plan_id in affected_plan_ids:
        plan_related = related_by_plan.get(plan_id, [])
        if not plan_related:
            continue
        plan_details_snap = [
            {'id': d.id, 'shipped_qty': d.shipped_qty}
            for d in plan_related
        ]
        old_value, new_value = _build_recalc_log_values(
            action_type, snapshot_before, extra_old_value, product_name,
            plan_id, plan_related, status_changes, plan_details_snap,
        )
        await _log_action(db, plan_id, action_type, old_value, new_value, operator or 'system')

    affected_plan_months = {p.plan_month for p in affected_plans if p.plan_month}
    return status_changes, len(affected_plans), affected_plan_months


async def recalc_plans_after_stockout_delete(db: AsyncSession, customer_name: str, product_name: str, stockout_no: str, deleted_quantity: int, *, operator: str = '') -> None:
    """
    出货记录删除后，重新计算关联出货计划的 shipped_qty 和状态

    由 stock_service.delete_stockout() 在删除出货记录后调用。
    不负责删除出货记录或提交事务——这些由调用方处理。

    流程：
    1. 找到受影响的计划：按 customer_name 匹配
    2. 重新 FIFO 分配，更新明细 shipped_qty
    3. 重新计算计划状态（completed → confirmed 回退）
    4. 记录回滚操作日志
    """
    # 先查询以获取快照，再调用公共逻辑（传入预查询数据避免重复 DB 访问）
    if not customer_name or not product_name:
        return

    plan_result = await db.execute(
        select(PurchasePlan).where(PurchasePlan.customer_name == customer_name)
    )
    affected_plans = plan_result.scalars().all()
    if not affected_plans:
        return

    affected_plan_ids = [p.id for p in affected_plans]

    detail_result = await db.execute(
        select(PurchasePlanDetail)
        .where(PurchasePlanDetail.plan_id.in_(affected_plan_ids))
        .order_by(PurchasePlanDetail.plan_date, PurchasePlanDetail.id)
        .with_for_update()
    )
    all_affected_details = detail_result.scalars().all()

    related_details = [d for d in all_affected_details if d.product_name == product_name]
    if not related_details:
        return

    # 快照回滚前的状态（用于日志）
    snapshot_before: dict[int, dict] = {}
    for d in related_details:
        snapshot_before[d.id] = {'id': d.id, 'plan_id': d.plan_id, 'quantity': d.quantity,
                                  'shipped_qty': d.shipped_qty, 'plan_date': str(d.plan_date)}

    status_changes, _, affected_plan_months = await _recalc_plans_common(
        db, customer_name, product_name,
        action_type='rollback_stockout',
        operator=operator,
        snapshot_before=snapshot_before,
        extra_old_value={'stockout_no': stockout_no, 'quantity': deleted_quantity},
        prefetched=(affected_plans, all_affected_details, related_details),
    )

    if affected_plan_months:
        async def _post_commit():
            for pm in affected_plan_months:
                await _invalidate_plan_caches(pm)
        _schedule_post_commit(db, _post_commit)

    logger.info(
        f'出货计划回滚完成：stockout_no={stockout_no}, '
        f'客户={customer_name}, 产品={product_name}, 数量={deleted_quantity}, '
        f'影响计划={len(affected_plans)}, 状态变更={status_changes}'
    )


async def recalc_plans_after_stockout_create(
    db: AsyncSession, customer_name: str, product_name: str, *, operator: str = ''
) -> None:
    """
    出货记录创建后，重新计算关联出货计划的 shipped_qty 和状态

    由 stock_service.create_stockout() 在创建出货记录后调用。
    不负责提交事务——这些由调用方处理。
    """
    status_changes, affected_count, affected_plan_months = await _recalc_plans_common(
        db, customer_name, product_name,
        action_type='recalc_stockout',
        operator=operator,
    )

    if affected_plan_months:
        async def _post_commit():
            for pm in affected_plan_months:
                await _invalidate_plan_caches(pm)
        _schedule_post_commit(db, _post_commit)

    logger.info(
        f'出货计划重算完成：客户={customer_name}, 产品={product_name}, '
        f'影响计划={affected_count}, 状态变更={status_changes}'
    )
