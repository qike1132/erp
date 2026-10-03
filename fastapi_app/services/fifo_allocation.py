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
import contextlib
import logging
from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from datetime import date, datetime
from typing import Any

from sqlalchemy import and_, event, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, load_only

from fastapi_app.core.cache import invalidate_local_cache
from fastapi_app.core.cache_invalidation import InvalidationStrategy, cache_mgr
from fastapi_app.core.redis_wrapper import safe_get, safe_set
from fastapi_app.shared_models import (
    DailyProductionRecord,
    Product,
    PurchasePlan,
    PurchasePlanDetail,
    StockOut,
)

logger = logging.getLogger(__name__)

FIFO_CACHE_PREFIX = 'plan_fifo'
FIFO_CACHE_TTL = 1800

# 生产量取数窗口的回看月数。
# 与出货的 SHIPMENT_RECORD_LOOKBACK_MONTHS = 12 不同，**不要顺手对齐成 12**：
# 出货量天然被该客户的实际发货量约束，而生产量是产品级的、可远超某个月的计划量，
# 12 个月无上界会让当月计划被历史累计产量全部填满、页面处处 100%。详见设计稿 §7。
PRODUCTION_RECORD_LOOKBACK_MONTHS = 1

# 生产量分配的 Redis 缓存前缀。与出货的 plan_fifo 分开：
# 两者数据源不同、失效触发也不同（出货看 StockOut，生产看 DailyProductionRecord），
# 共用一个前缀会让任一侧的失效把另一侧的缓存也清掉，也会让脏数据的诊断无从分辨。
PRODUCTION_FIFO_CACHE_PREFIX = 'plan_prod_fifo'


async def _invalidate_fifo_cache(plan_month: str) -> None:
    """清除指定月份的 FIFO 缓存

    N5 修复：使用 KEYS 策略直接删除精确键，而非 PATTERN（无通配符的 pattern 语义混淆）。
    PATTERN 适用于通配符匹配；这里缓存键是精确的 `plan_fifo:YYYY-MM`，应使用 KEYS。
    """
    cache_key = f'{FIFO_CACHE_PREFIX}:{plan_month}'
    await cache_mgr.invalidate(InvalidationStrategy.KEYS, [cache_key])


async def _invalidate_production_fifo_cache(plan_month: str) -> None:
    """清除指定月份的生产量分配缓存（与出货缓存分开，键前缀不同）"""
    await cache_mgr.invalidate(InvalidationStrategy.KEYS, [f'{PRODUCTION_FIFO_CACHE_PREFIX}:{plan_month}'])


# ==================== 出货/生产记录写入 → 分配缓存失效（集中钩子，M2 修复） ====================
# 出货/退货/出货修改/出货删除/批量导入都会改变 FIFO 的"累计出货净量"，生产记录的增删改
# 会改变生产量，但写路径分散在多个服务中，逐点挂钩易漏。改为 SQLAlchemy 会话事件集中
# 钩子：任何事务提交前检测到 StockOut 变更，提交后即清除全部 plan_fifo:* 缓存；
# 检测到 StockOut 或 DailyProductionRecord 变更，则两个前缀一起清。
# after_commit 时数据已落库，此后任何缓存重建读到的都是已提交数据（无回填旧值窗口）；
# 若失效失败仅告警，由 TTL（FIFO_CACHE_TTL）兜底。_fifo_after_commit 无需改动 ——
# 它只消费 `fifo_dirty` 这一个标记，来源多寡与它无关。
#
# 注意：此处不能用模块级全局布尔标记（曾为 `_pending_fifo_invalidation`）。并发事务会
# 共享同一全局标志：T1 提交置 True → T2 的 before_commit 见 True 提前返回 → T1 清 False
# → T2 的 after_commit 见 False 跳过失效，导致 T2 的 StockOut 变更 FIFO 缓存永不失效
# （静默数据不一致）。改用 session.info（每会话独立）承载标记。


def _fifo_before_commit(session) -> None:
    # 一个标记覆盖两种来源：会话里只要动过出货记录或生产记录，提交后就清两个分配前缀。
    # 分开标记会让「同一事务既改出货又改生产」需要两处判断，收益不抵复杂度；
    # 生产记录写入频率远低于出货，多清一次的代价可忽略。
    # 另记 produced_dirty：生产量还进了聚合响应缓存（pp:*），那条链路的失效
    # 不像出货那样有 shipment recalc 兜着，得由这里补（见 _invalidate_fifo_caches_safe）。
    if session.info.get('fifo_dirty'):
        return
    for obj in list(session.new) + list(session.dirty) + list(session.deleted):
        if isinstance(obj, DailyProductionRecord):
            session.info['produced_dirty'] = True
            session.info['fifo_dirty'] = True
        elif isinstance(obj, StockOut):
            session.info['fifo_dirty'] = True


# 后台任务强引用集合：asyncio 对 Task 仅持弱引用，不保存引用会被 GC 中途回收（官方文档警告）。
_background_tasks: set[asyncio.Task] = set()


def _fifo_after_commit(session) -> None:
    if not session.info.get('fifo_dirty'):
        return
    session.info['fifo_dirty'] = False
    produced_dirty = session.info.pop('produced_dirty', False)
    task = asyncio.get_running_loop().create_task(_invalidate_fifo_caches_safe(produced_dirty))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _invalidate_fifo_caches_safe(produced_dirty: bool = False) -> None:
    try:
        await cache_mgr.invalidate(InvalidationStrategy.PATTERN, ['plan_fifo:*'])
        await cache_mgr.invalidate(InvalidationStrategy.PATTERN, [f'{PRODUCTION_FIFO_CACHE_PREFIX}:*'])
        invalidate_local_cache('plan_fifo:*')
        invalidate_local_cache(f'{PRODUCTION_FIFO_CACHE_PREFIX}:*')
        if produced_dirty:
            # 生产量进了聚合响应（rows / sku_summary / customers 的 produced_*），
            # 只清分配缓存不够：页面读的是 pp:* 聚合，TTL 120s（本地 30s）内会一直显示旧值，
            # 「录入生产记录 → 刷新页面应变」的人工验收会因此假失败。
            # 出货写入不在这里清 pp:* —— 那条链路已由 shipment recalc 调 _invalidate_plan_caches。
            await cache_mgr.invalidate(InvalidationStrategy.PATTERN, ['pp:*'])
            invalidate_local_cache('pp:*')
    except Exception:  # defensive: 缓存失效失败不阻断业务，靠 TTL 兜底
        logger.warning("分配缓存全量失效失败（等待 TTL 过期兜底）", exc_info=True)


event.listen(Session, "before_commit", _fifo_before_commit)
event.listen(Session, "after_commit", _fifo_after_commit)


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
            try:
                cached_int_keys = {int(k) for k in cached}
            except (ValueError, TypeError):
                # L2 修复：缓存脏数据（键不可转 int）视为未命中并清除，不让其演变为 500
                await _invalidate_fifo_cache(plan_month)
                cached = None
            else:
                detail_ids = {d.id for d in plan_details}
                if detail_ids.issubset(cached_int_keys):
                    return {int(k): v for k, v in cached.items()}

    try:
        result = await _fifo_query_with_timeout(db, plan_details, customer_name_map, plan_month)
        return result
    except TimeoutError:
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
        with contextlib.suppress(SQLAlchemyError, OSError):
            await db.execute(text("RESET statement_timeout"))
        logger.exception('FIFO查询异常: %s', e)
        raise RuntimeError('FIFO_ALLOCATION_UNAVAILABLE') from e


async def _build_fifo_plan_id_to_customer(db: AsyncSession, customer_name_map: dict | None, plan_details: list, customers: list, earliest_plan_date) -> dict:
    plan_ids_in_details = {d.plan_id for d in plan_details}
    if customer_name_map and plan_ids_in_details.issubset(customer_name_map.keys()):
        plan_id_to_customer = {pid: customer_name_map[pid] for pid in plan_ids_in_details if customer_name_map.get(pid)}
    else:
        # 查询相关主单 — 只取 id + customer_name，限制时间范围避免全表扫描
        plan_result = await db.execute(
            select(PurchasePlan.id, PurchasePlan.customer_name)
            .where(
                PurchasePlan.customer_name.in_(customers),
                # 字符串比较 "YYYY-MM" >= "YYYY-MM" 依赖字典序，
                # 在固定位数（年4位+月2位）格式下等价于日期比较，安全可用
                PurchasePlan.plan_month >= f"{earliest_plan_date.year - 1}-{earliest_plan_date.month:02d}",
            )
        )
        all_plan_rows = plan_result.all()
        plan_id_to_customer = {r.id: r.customer_name for r in all_plan_rows}
    return plan_id_to_customer


def _group_fifo_details_by_key(all_details: Sequence, plan_id_to_customer: Mapping, keys_needed: AbstractSet) -> dict[tuple, list]:
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
    return details_by_key


async def _query_fifo_stockout_rows(db: AsyncSession, keys_needed: set, customers: list, product_ids: list, stockout_date_limit) -> tuple:
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
    return stockout_result, pid_to_name


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
        with contextlib.suppress(SQLAlchemyError, OSError):
            await db.execute(text("SET LOCAL statement_timeout = '8s'"))

        # S3: 若调用方已传入 customer_name_map 且覆盖了所有 plan_id，跳过本次 PurchasePlan 查询
        plan_id_to_customer = await _build_fifo_plan_id_to_customer(db, customer_name_map, plan_details, customers, earliest_plan_date)

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
        details_by_key = _group_fifo_details_by_key(all_details, plan_id_to_customer, keys_needed)

        stockout_result, pid_to_name = await _query_fifo_stockout_rows(db, keys_needed, customers, product_ids, stockout_date_limit)

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


def aggregate_produced_by_product(rows: Sequence) -> dict[int, int]:
    """生产记录行 → {product_id: 累计生产量}。

    - 按 product_id 聚合，不按 department 过滤：三部门（充棉/手工/包装）相加，
      与 daily_production_service 的月度汇总口径一致。
    - product_id 为空的行丢弃：daily_production_record.product_id 可空，
      空值无法与计划明细关联，沿用 stock_inventory_service 的
      `WHERE product_id IS NOT NULL` 惯例。
    - quantity 为 NULL 按 0 计：避免 None 参与加法抛 TypeError。
    """
    out: dict[int, int] = {}
    for row in rows:
        if not row.product_id:
            continue
        out[row.product_id] = out.get(row.product_id, 0) + int(row.quantity or 0)
    return out


def production_window(plan_month: str, now: datetime) -> tuple[date, date]:
    """生产量取数窗口 [计划月首 − 1 个月, 现在]（定案：设计稿 §7 乙）。

    - 下界回看 1 个月：计划日落在月初时，生产往往在上月末完成（先产后出）。
    - 上界取「现在」而非「计划月末」：本页是跟踪工具，历史月份的完成率应随后续
      生产继续上升；取月末会把数字冻结在过去。
    用月序换算而非 timedelta(days=30)：后者在 2 月与大月之间会漂移出月份。
    """
    year, month = map(int, plan_month.split('-'))
    m = month - PRODUCTION_RECORD_LOOKBACK_MONTHS
    y = year
    while m < 1:
        m += 12
        y -= 1
    return date(y, m, 1), now.date()


def group_details_by_product(all_details: Sequence) -> dict[int, list]:
    """计划明细按 product_id 分组，保持传入顺序。

    调用方负责先按 (plan_date, id) 排序 —— allocate_fifo 的摊派顺序即传入顺序，
    这里重排会让同 plan_date 的分配结果不可复现。
    product_id 为空的明细无法关联生产记录，丢弃。
    """
    out: dict[int, list] = {}
    for d in all_details:
        if not d.product_id:
            continue
        out.setdefault(d.product_id, []).append(d)
    return out


def allocate_fifo(
    plan_details: Sequence,
    details_by_key: Mapping[Any, list],
    total_by_key: Mapping[Any, int],
) -> dict[int, int]:
    """A1: FIFO 分配纯函数（核心算法，可独立单元测试）

    对每个键：
        1. 取该键的所有计划明细（已按 plan_date ASC 排序）
        2. 取该键的累计量（出货净量，或生产量 —— 由调用方决定语义）
        3. 用累计分配法：累计量按顺序依次填满最早的计划

    Args:
        plan_details: 当前查询涉及的计划明细列表（用于补零）
        details_by_key: {键: [PurchasePlanDetail, ...]} 已分组+排序。
            出货路径的键是 (customer_name, product_name)，生产路径的键是 product_id。
        total_by_key: {键: 累计量}

    Returns:
        {plan_detail_id: allocated_qty}
    """
    allocated: dict[int, int] = {}
    for key, details in details_by_key.items():
        total_shipped = total_by_key.get(key, 0)
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


async def _month_details_for_products(db: AsyncSession, plan_month: str, product_ids: list) -> list:
    """取「该月内这些产品」的全部计划明细，按 (plan_date, id) 排序 —— FIFO 摊派的作用域。

    与出货版把作用域放宽到「相关主单的全部明细」同理：子集视图（某天 / 某客户）
    必须落在同一份摊派结果上，否则同一行在不同视图里数字不一致。
    """
    result = await db.execute(
        select(PurchasePlanDetail)
        .options(load_only(
            PurchasePlanDetail.id, PurchasePlanDetail.plan_id,
            PurchasePlanDetail.product_name, PurchasePlanDetail.product_id,
            PurchasePlanDetail.plan_date, PurchasePlanDetail.quantity,
        ))
        .join(PurchasePlan, PurchasePlanDetail.plan_id == PurchasePlan.id)
        .where(
            PurchasePlan.plan_month == plan_month,
            PurchasePlanDetail.product_id.in_(product_ids),
        )
        .order_by(PurchasePlanDetail.plan_date, PurchasePlanDetail.id)
    )
    return list(result.scalars().all())


async def _get_produced_fifo_map(db: AsyncSession, plan_details: list, plan_month: str = '') -> dict[int, int]:
    """把窗口内的生产量摊到计划明细上。

    与出货版的差别只有两点：
      1. 分组键是 product_id（生产记录没有客户字段），不是 (customer, product_name)
      2. 累计量来自 daily_production_record，窗口见 production_window

    契约与出货版一致：查询超时/异常抛 RuntimeError('FIFO_ALLOCATION_UNAVAILABLE')，
    由 _get_produced_fifo_map_safe 捕获后标记降级，而不是返回全 0 让业务误读成「没生产」。

    返回: {plan_detail_id: allocated_produced_qty}
    """
    if not plan_details:
        return {}

    cache_key = f'{PRODUCTION_FIFO_CACHE_PREFIX}:{plan_month}' if plan_month else ''
    if cache_key:
        cached = await safe_get(cache_key, context='生产量分配缓存')
        if cached is not None:
            try:
                cached_int_keys = {int(k) for k in cached}
            except (ValueError, TypeError):
                # 缓存脏数据视为未命中并清除，不让其演变为 500（同出货版 L2 修复）
                await _invalidate_production_fifo_cache(plan_month)
                cached = None
            else:
                if {d.id for d in plan_details}.issubset(cached_int_keys):
                    full = {int(k): v for k, v in cached.items()}
                    return {d.id: full.get(d.id, 0) for d in plan_details}

    try:
        async with asyncio.timeout(10):
            product_ids = sorted({d.product_id for d in plan_details if d.product_id})
            if not product_ids:
                # 全是历史脏数据（product_id 为空）→ 无从关联生产记录
                return {}

            start, end = production_window(plan_month, datetime.now())

            with contextlib.suppress(SQLAlchemyError, OSError):
                await db.execute(text("SET LOCAL statement_timeout = '8s'"))

            result = await db.execute(
                select(
                    DailyProductionRecord.product_id,
                    func.sum(DailyProductionRecord.quantity).label('quantity'),
                )
                .where(
                    and_(
                        DailyProductionRecord.product_id.in_(product_ids),
                        DailyProductionRecord.production_date >= start,
                        DailyProductionRecord.production_date <= end,
                    )
                )
                .group_by(DailyProductionRecord.product_id)
            )
            # 别名取 quantity，让纯聚合函数在「原始行」与「分组行」两种输入上通用
            produced_by_key = aggregate_produced_by_product(result.all())

            # 摊派必须落在「该月该产品的全部明细」上，而不是调用方传进来的子集 ——
            # get_day_details 只传当天、带 customer_id 的调用只传该客户；若就着子集摊派，
            # 被传进来的行会独吞整个窗口的产量，同一个计划行在月历与弹窗里给出不同数字。
            # 出货路径同理（它把 all_details 放宽到相关主单的全部明细）。
            scope_details = (
                await _month_details_for_products(db, plan_month, product_ids)
                if plan_month else plan_details
            )
            allocated = allocate_fifo(
                scope_details,
                group_details_by_product(scope_details),
                produced_by_key,
            )
    except TimeoutError:
        with contextlib.suppress(SQLAlchemyError, OSError):
            await db.execute(text("RESET statement_timeout"))
        logger.exception('生产量分配查询超时 plan_month=%s', plan_month)
        raise RuntimeError('FIFO_ALLOCATION_UNAVAILABLE') from None
    except Exception as e:  # defensive: 同出货版，异常时抛明确异常交由调用方降级
        with contextlib.suppress(SQLAlchemyError, OSError):
            await db.execute(text("RESET statement_timeout"))
        logger.exception('生产量分配查询异常: %s', e)
        raise RuntimeError('FIFO_ALLOCATION_UNAVAILABLE') from e

    # 缓存按「月份级存全体」：allocated 覆盖该月该产品的所有明细行，
    # 于是任何子集视图（某天 / 某客户）命中缓存后都能取到自己那几行的正确值。
    if cache_key:
        await safe_set(cache_key, {str(k): v for k, v in allocated.items()},
                       timeout=FIFO_CACHE_TTL, context='生产量分配缓存')

    return {d.id: allocated.get(d.id, 0) for d in plan_details}
