"""
FIFO 分配算法

职责：采购计划明细的 FIFO（先进先出）出货分配算法。
独立拆出便于单元测试，是采购计划出货量计算的核心算法。

算法说明：
    对每个 (customer, product) 对：
    1. 查出该客户+产品的所有计划明细（不限当月），按 plan_date ASC 排序
    2. 查出该客户+产品的出货记录（最早计划往前12个月），按 stockout_date ASC 排序
    3. 用累计分配法：出货总量按顺序依次填满最早的计划

从 purchase_plan_service.py 拆分而来，保持函数签名不变。
"""
import asyncio
import logging
from datetime import date, datetime

from sqlalchemy import and_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from fastapi_app.core.cache_invalidation import InvalidationStrategy, cache_mgr
from fastapi_app.core.redis_wrapper import safe_get, safe_set
from fastapi_app.shared_models import (
    Product,
    PurchasePlan,
    PurchasePlanDetail,
    StockOut,
)

logger = logging.getLogger(__name__)

FIFO_CACHE_PREFIX = 'plan_fifo'
FIFO_CACHE_TTL = 1800


async def _invalidate_fifo_cache(plan_month: str) -> None:
    """清除指定月份的 FIFO 缓存

    N5 修复：使用 KEYS 策略直接删除精确键，而非 PATTERN（无通配符的 pattern 语义混淆）。
    PATTERN 适用于通配符匹配；这里缓存键是精确的 `plan_fifo:YYYY-MM`，应使用 KEYS。
    """
    cache_key = f'{FIFO_CACHE_PREFIX}:{plan_month}'
    await cache_mgr.invalidate(InvalidationStrategy.KEYS, [cache_key])


async def _get_shipped_fifo_map(db: AsyncSession, plan_details: list, customer_name_map: dict | None = None, plan_month: str = '') -> dict[int, int]:
    """
    FIFO 分配出货数量到计划明细

    对每个 (customer, product) 对：
    1. 查出该客户+产品的所有计划明细（不限当月），按 plan_date ASC 排序
    2. 查出该客户+产品的出货记录（最早计划往前12个月），按 stockout_date ASC 排序
    3. 用累计分配法：出货总量按顺序依次填满最早的计划

    参数:
        plan_details: 当前查询涉及的计划明细列表（PurchasePlanDetail 对象）
        customer_name_map: {plan_id: customer_name} 映射，用于关联主单客户名
        plan_month: 计划月份 "YYYY-MM"，用于缓存键

    返回: {plan_detail_id: allocated_shipped_qty}
    """
    if not plan_details:
        return {}

    # 尝试从 Redis 缓存读取
    if plan_month:
        cache_key = f'{FIFO_CACHE_PREFIX}:{plan_month}'
        cached = await safe_get(cache_key, context='FIFO缓存')
        if cached is not None:
            cached_int_keys = {int(k) for k in cached}
            detail_ids = {d.id for d in plan_details}
            if detail_ids.issubset(cached_int_keys):
                return {int(k): v for k, v in cached.items()}

    try:
        result = await _fifo_query_with_timeout(db, plan_details, customer_name_map, plan_month)
        return result
    except asyncio.TimeoutError:
        # SET LOCAL 在 ROLLBACK 后自动重置，但异常路径下连接可能未正确 ROLLBACK
        # 显式 RESET 防止 statement_timeout 污染后续查询
        try:
            await db.execute(text("RESET statement_timeout"))
        except (SQLAlchemyError, OSError):
            logger.warning("RESET statement_timeout 失败，连接可能被污染", exc_info=True)
        logger.exception('FIFO查询超时 plan_month=%s', plan_month)
        # 不再返回全 0 降级值（会被业务误读为"无出货"），改为抛出明确异常，
        # 由调用方决定降级策略（显式标记或失败）
        raise RuntimeError('FIFO_ALLOCATION_UNAVAILABLE') from None
    except Exception as e:  # defensive: FIFO查询异常时抛出明确异常，由调用方决定降级策略
        try:
            await db.execute(text("RESET statement_timeout"))
        except (SQLAlchemyError, OSError):
            pass
        logger.exception('FIFO查询异常: %s', e)
        raise RuntimeError('FIFO_ALLOCATION_UNAVAILABLE') from e


async def _fifo_query_with_timeout(db: AsyncSession, plan_details: list, customer_name_map: dict | None, plan_month: str) -> dict[int, int]:
    """FIFO 查询核心逻辑，带超时保护

    S3 修复：若调用方已传入 customer_name_map（{plan_id: customer_name}），
    复用该映射，避免再次查询 PurchasePlan 表。
    """
    async with asyncio.timeout(10):
        # 收集所有需要查询的 (customer_name, product_name) 对
        keys_needed = set()
        product_ids_needed = set()
        for d in plan_details:
            cname = customer_name_map.get(d.plan_id, '') if customer_name_map else ''
            if cname and d.product_name:
                keys_needed.add((cname, d.product_name))
            if d.product_id:
                product_ids_needed.add(d.product_id)

        if not keys_needed:
            return {}

        # 去重（P1-01: IN列表保护）
        customers = list({k[0] for k in keys_needed})
        product_ids = list(product_ids_needed)

        # P0-01: 计算日期下限——取所有相关明细中最早的plan_date往前推12个月
        # P1-NEW-01: 转为datetime类型，确保与StockOut.stockout_date(DateTime)比较时索引可用
        earliest_plan_date = min((d.plan_date for d in plan_details if d.plan_date), default=date.today())
        # 用replace减年，避免闰年timedelta(days=365)偏移
        try:
            limit_date = earliest_plan_date.replace(year=earliest_plan_date.year - 1)
        except ValueError:
            limit_date = earliest_plan_date.replace(year=earliest_plan_date.year - 1, day=28)
        stockout_date_limit = datetime(limit_date.year, limit_date.month, limit_date.day)

        # 设置服务端查询超时：SET LOCAL 仅在当前事务内生效，COMMIT/ROLLBACK 后自动重置
        try:
            await db.execute(text("SET LOCAL statement_timeout = '8s'"))
        except (SQLAlchemyError, OSError):
            pass

        # S3: 若调用方已传入 customer_name_map 且覆盖了所有 plan_id，跳过本次 PurchasePlan 查询
        # 检查 customer_name_map 是否覆盖了所有 plan_details 的 plan_id
        plan_ids_in_details = {d.plan_id for d in plan_details}
        if customer_name_map and plan_ids_in_details.issubset(customer_name_map.keys()):
            plan_id_to_customer = {pid: customer_name_map[pid] for pid in plan_ids_in_details if customer_name_map.get(pid)}
        else:
            # 查询相关主单 — 只取 id + customer_name，限制时间范围避免全表扫描
            plan_result = await db.execute(
                select(PurchasePlan.id, PurchasePlan.customer_name)
                .where(
                    PurchasePlan.customer_name.in_(customers),
                    PurchasePlan.plan_month >= f"{earliest_plan_date.year - 1}-{earliest_plan_date.month:02d}",
                )
            )
            all_plan_rows = plan_result.all()
            plan_id_to_customer = {r.id: r.customer_name for r in all_plan_rows}

        # 查询相关主单的所有明细 — 只取 FIFO 需要的字段
        relevant_plan_ids = list(plan_id_to_customer.keys())
        if not relevant_plan_ids:
            return {}

        detail_result = await db.execute(
            select(PurchasePlanDetail)
            .options(load_only(
                PurchasePlanDetail.id, PurchasePlanDetail.plan_id,
                PurchasePlanDetail.product_name, PurchasePlanDetail.product_id,
                PurchasePlanDetail.plan_date, PurchasePlanDetail.quantity,
            ))
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

        # 查出这些客户+产品的出货记录
        # 双分支是有意识的性能优化，非冗余：
        #   - product_id 路径：用 product_id IN(...) 避免 JOIN Product，命中
        #     idx_stockout_product_customer_type 索引，适合明细已关联 product_id 的常规场景。
        #   - JOIN 降级路径：仅当所有明细 product_id=0（历史脏数据）时触发，用
        #     Product.name IN(...) 兜底匹配。
        # 统一为单一路径会牺牲常规场景性能，请勿合并。
        pid_to_name: dict[int, str] = {}
        if not product_ids:
            # 降级：无 product_id 时 JOIN Product 按 name 匹配
            product_names = list({k[1] for k in keys_needed})
            stockout_result = await db.execute(
                select(StockOut.customer, Product.name.label('product_name'), StockOut.quantity, StockOut.returned_quantity, StockOut.stockout_date)
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
        else:
            # 优先用 product_id 查询，避免 JOIN Product 表的额外开销
            # 先查 stock_out，再在内存中用 product_id → product_name 映射关联
            stockout_result = await db.execute(
                select(StockOut.customer, StockOut.product_id, StockOut.quantity, StockOut.returned_quantity, StockOut.stockout_date)
                .where(
                    and_(
                        StockOut.customer.in_(customers),
                        StockOut.product_id.in_(product_ids),
                        StockOut.customer.isnot(None),
                        StockOut.customer != '',
                        StockOut.stockout_date >= stockout_date_limit,
                    )
                )
                .order_by(StockOut.stockout_date, StockOut.id)
            )
            # 构建 product_id → product_name 映射
            pid_result = await db.execute(select(Product.id, Product.name).where(Product.id.in_(product_ids)))
            pid_to_name = {r.id: r.name for r in pid_result.all()}

        stockout_rows = stockout_result.all()

        # 构建 product_id → product_name 完整映射（优先用 Product 表，fallback 用计划明细的 product_name）
        if product_ids:
            # 补充：pid_to_name 中缺失的 product_id，用计划明细中的 product_name 填充
            detail_pid_to_name: dict[int, str] = {}
            for d in all_details:
                if d.product_id and d.product_name and d.product_id not in detail_pid_to_name:
                    detail_pid_to_name[d.product_id] = d.product_name
            for pid, pname in detail_pid_to_name.items():
                if pid not in pid_to_name:
                    pid_to_name[pid] = pname

        # 按 (customer, product_name) 分组，累计出货总量
        shipped_by_key = _aggregate_shipped_by_key(stockout_rows, product_ids, pid_to_name)

        # A1: 调用纯函数执行 FIFO 分配（可独立单元测试）
        allocated = allocate_fifo(plan_details, details_by_key, shipped_by_key)

        # 写入 Redis 缓存
        if plan_month:
            cache_key = f'{FIFO_CACHE_PREFIX}:{plan_month}'
            cacheable = {str(k): v for k, v in allocated.items()}
            await safe_set(cache_key, cacheable, timeout=FIFO_CACHE_TTL, context='FIFO缓存')

        return allocated


def _aggregate_shipped_by_key(stockout_rows: list, product_ids: list, pid_to_name: dict[int, str]) -> dict[tuple[str, str], int]:
    """按 (customer, product_name) 分组，累计出货净量（quantity - returned_quantity）

    A1 提取的纯函数：将 stockout 行聚合为 {(customer, product_name): total_qty}。
    """
    shipped_by_key: dict[tuple, int] = {}
    for row in stockout_rows:
        if product_ids:
            pname = pid_to_name.get(row.product_id, '')
        else:
            pname = row.product_name
        key = (row.customer, pname)
        shipped_by_key[key] = shipped_by_key.get(key, 0) + (row.quantity - row.returned_quantity)
    return shipped_by_key


def allocate_fifo(
    plan_details: list,
    details_by_key: dict[tuple[str, str], list],
    shipped_by_key: dict[tuple[str, str], int],
) -> dict[int, int]:
    """A1: FIFO 分配纯函数（核心算法，可独立单元测试）

    对每个 (customer, product) 对：
        1. 取该 key 的所有计划明细（已按 plan_date ASC 排序）
        2. 取该 key 的累计出货净量
        3. 用累计分配法：出货总量按顺序依次填满最早的计划

    Args:
        plan_details: 当前查询涉及的计划明细列表（用于补零）
        details_by_key: {(customer, product): [PurchasePlanDetail, ...]} 已分组+排序
        shipped_by_key: {(customer, product): total_shipped_qty} 累计出货净量

    Returns:
        {plan_detail_id: allocated_shipped_qty}
    """
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
