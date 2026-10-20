"""
湖北订单+备货合并查询与确认（beile-order 页面）

从 order_crud.py 按职责拆出，行为与原实现完全一致。
"""
import logging
from datetime import UTC, datetime
from typing import NamedTuple

from sqlalchemy import and_, desc, func, literal, or_, select, union_all, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from fastapi_app.core.cache import cache_result
from fastapi_app.core.exceptions import ConflictError, NotFoundError
from fastapi_app.services import escape_like
from fastapi_app.services.notification_service import BEILE_UNCONFIRMED_TYPE
from fastapi_app.services.purchase_order_sku import po_sku_available
from fastapi_app.services.purchase_utils import parse_source_order_ids
from fastapi_app.shared.time_format import format_local_time
from fastapi_app.shared_models import (
    Notification,
    Order,
    OrderItem,
    Product,
    PurchaseOrder,
    PurchaseOrderSku,
    PurchaseOrderStatus,
    StockIn,
    User,
)

logger = logging.getLogger(__name__)

# 未在采购中心完成下单时拒绝确认的统一文案（与前端 NOT_ORDERED_DETAIL 逐字一致，设计 §11.4）
BEILE_NOT_ORDERED_DETAIL = '该订单未在采购中心完成下单，请先在采购中心完成下单后再确认'

# beile-list 时间展示统一走 shared.time_format（UTC→北京时间）。
# order_date / stockin_date 列为 timestamptz（DB 存储 UTC）、confirmed_at 列为 naive
# TIMESTAMP 且写入的是 naive UTC（confirm_* 写入处 now(UTC).replace(tzinfo=None)）。
def _fmt_beile_time(dt: datetime | None) -> str:
    """UTC（aware timestamptz 或 naive UTC）→ 北京时间 'YYYY-MM-DD HH:MM'。"""
    return format_local_time(dt, '%Y-%m-%d %H:%M') or ''


def _build_beile_unified_query(confirmed: bool | None, customer, factory, product_kw=None):
    """构建 Order+StockIn 的 UNION ALL 子查询。

    confirmed: None=不过滤确认状态；False=仅未确认；True=仅已确认。
    订单与备货均按各自表的 confirmed_at 过滤。
    """
    # ---- 构建 UNION ALL 子查询 ----
    # Order 部分：未删除订单，通过 order_item.product.factory 筛选
    order_part = select(
        literal('order').label('record_type'),
        Order.id.label('source_id'),
        Order.order_no.label('order_no'),
        Order.customer.label('customer'),
        Order.order_date.label('sort_date'),
    ).where(
        Order.is_deleted.isnot(True),
        Order.items.any(OrderItem.product.has(Product.factory == factory)),
    )
    if confirmed is not None:
        order_part = order_part.where(
            Order.confirmed_at.isnot(None) if confirmed else Order.confirmed_at.is_(None)
        )
    if customer:
        order_part = order_part.where(Order.customer.like(f'%{escape_like(customer)}%'))
    if product_kw:
        kw = f'%{escape_like(product_kw)}%'
        # 订单侧：**本厂** SKU 的 product_name / product_barcode 命中。
        # 工厂条件必须与关键字条件合并在同一个 any()：两个独立的 any() 会让
        # 「关键字命中他厂 SKU、本厂 SKU 不命中」的混工厂单误入选（生产 BUG 2026-10-15）
        order_part = order_part.where(
            Order.items.any(and_(
                OrderItem.product.has(Product.factory == factory),
                or_(OrderItem.product_name.ilike(kw), OrderItem.product_barcode.ilike(kw)),
            ))
        )

    # StockIn 部分：通过 product.factory 筛选（备货同样参与确认状态筛选）
    stockin_part = select(
        literal('stockin').label('record_type'),
        StockIn.id.label('source_id'),
        StockIn.stockin_no.label('order_no'),
        StockIn.customer.label('customer'),
        StockIn.stockin_date.label('sort_date'),
    ).where(
        StockIn.product.has(Product.factory == factory),
    )
    if confirmed is not None:
        stockin_part = stockin_part.where(
            StockIn.confirmed_at.isnot(None) if confirmed else StockIn.confirmed_at.is_(None)
        )
    if customer:
        stockin_part = stockin_part.where(StockIn.customer.like(f'%{escape_like(customer)}%'))
    if product_kw:
        kw = f'%{escape_like(product_kw)}%'
        # 备货侧：产品 name / barcode 命中
        stockin_part = stockin_part.where(
            StockIn.product.has(or_(Product.name.ilike(kw), Product.barcode.ilike(kw)))
        )

    parts = [order_part, stockin_part]
    return union_all(*parts).subquery()


async def _fetch_beile_records_by_ids(db: AsyncSession, order_ids: list[int], stockin_ids: list[int]) -> tuple:
    orders_map: dict[int, Order] = {}
    if order_ids:
        order_result = await db.execute(
            select(Order)
            .options(
                joinedload(Order.confirmed_by),
                selectinload(Order.items).joinedload(OrderItem.product),
            )
            .where(Order.id.in_(order_ids))
        )
        for o in order_result.scalars().unique():
            orders_map[o.id] = o

    stockins_map: dict[int, StockIn] = {}
    if stockin_ids:
        stockin_result = await db.execute(
            select(StockIn)
            .options(
                joinedload(StockIn.product),
                joinedload(StockIn.confirmed_by),
            )
            .where(StockIn.id.in_(stockin_ids))
        )
        for s in stockin_result.scalars():
            stockins_map[s.id] = s

    return orders_map, stockins_map


async def _fetch_completed_po_maps(
    db: AsyncSession,
) -> tuple[dict[int, list], dict[tuple[str, str], list], dict[int, object]]:
    """一次查询 completed 采购单，内存建三套映射（无 N+1，仅取必要列）。

    返回：
      by_order_id[order_id] = [row, ...]
          由 `source_order_ids` 精确元素匹配（**非 LIKE**，规避 '6509' 误命中 '[65091]'）。
          **语义不变**，order 路径零变化。
      by_customer_product[(customer, product_name)] = [row, ...]
          供备货行**模糊**匹配（PRD Q2 采纳的规则）。**该匹配只决定 `is_ordered`
          信号，绝不决定数量**（数量口径见 :func:`_apply_ordered_fields` 的 pos_exact 契约）。
      po_by_id[po_id] = row
          按采购单主键反查同一轻量行，供备货**精确（带类型）匹配**按去重后的 po_id 取用
          （与 ``purchase_order_sku.source_record_type`` 配合，精确区分 order / stockin）。

    全库 completed 采购单量级极小（数十条），一次全量拉取成本可忽略，
    且彻底规避 SQL 侧 JSON 解析的类型 / 转义风险（设计 §5.2）。
    超过 1000 条视为量级异常（缓存 TTL 内每次列表查询都会全量拉取），告警日志提示改分页聚合。
    """
    rows = (await db.execute(
        select(
            PurchaseOrder.id,  # 供逐 SKU 快照做「覆盖完整性」比对（缺列会误判为未覆盖）
            PurchaseOrder.source_order_ids,
            PurchaseOrder.customer_name,
            PurchaseOrder.product_name,
            PurchaseOrder.product_quantity,
            PurchaseOrder.spare_quantity,
            PurchaseOrder.spare_rate,
        ).where(PurchaseOrder.status == PurchaseOrderStatus.COMPLETED)
    )).all()
    if len(rows) > 1000:
        logger.warning('completed 采购单已达 %s 条（>1000），_fetch_completed_po_maps 全量内存建映射应改为分页聚合', len(rows))

    by_order_id: dict[int, list] = {}
    by_customer_product: dict[tuple[str, str], list] = {}
    po_by_id: dict[int, object] = {}
    for r in rows:
        for oid in parse_source_order_ids(r.source_order_ids):
            by_order_id.setdefault(oid, []).append(r)
        by_customer_product.setdefault((r.customer_name or '', r.product_name or ''), []).append(r)
        po_by_id[r.id] = r
    return by_order_id, by_customer_product, po_by_id


class _PoSkuRow(NamedTuple):
    """completed 采购单的一条逐 SKU 快照（读路径内存视图，避免 ORM 懒加载）。"""

    po_id: int
    product_name: str
    order_qty: float
    spare_qty: float
    spare_rate: float | None


def _norm_name(value) -> str:
    """产品名归一化：strip + 大小写折叠，规避同一 SKU 因空白/大小写差异匹配失败。"""
    return str(value or '').strip().casefold()


async def _fetch_po_sku_maps(db: AsyncSession) -> tuple[dict, dict]:
    """一次查询 completed 采购单的逐 SKU 快照，内存建映射（无 N+1）。

    - ``sku_by_source[(record_type, source_id)] = [_PoSkuRow, ...]``：按来源精确匹配；
    - ``sku_by_po_id[po_id] = [_PoSkuRow, ...]``：按采购单聚合（备货近似路径备用）。

    表缺失（迁移未执行）时优雅降级为空映射 → 行注入回退订单级口径，绝不抛错。
    """
    empty: tuple[dict, dict] = ({}, {})
    if not await po_sku_available(db):
        return empty
    try:
        async with db.begin_nested():
            rows = (await db.execute(
                select(
                    PurchaseOrderSku.po_id,
                    PurchaseOrderSku.product_name,
                    PurchaseOrderSku.order_qty,
                    PurchaseOrderSku.spare_qty,
                    PurchaseOrderSku.spare_rate,
                    PurchaseOrderSku.source_order_id,
                    PurchaseOrderSku.source_record_type,
                )
                .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderSku.po_id)
                .where(PurchaseOrder.status == PurchaseOrderStatus.COMPLETED)
            )).all()
    except Exception:  # defensive: 表缺失/方言差异一律降级为「无逐 SKU 数据」
        logger.warning('读取 purchase_order_sku 失败，逐 SKU 注入降级为订单级口径', exc_info=True)
        return empty

    sku_by_source: dict[tuple[str, int], list] = {}
    sku_by_po_id: dict[int, list] = {}
    for r in rows:
        if r.source_order_id is None:
            continue
        row = _PoSkuRow(
            po_id=r.po_id,
            product_name=r.product_name or '',
            order_qty=float(r.order_qty or 0),
            spare_qty=float(r.spare_qty or 0),
            spare_rate=float(r.spare_rate) if r.spare_rate is not None else None,
        )
        sku_by_source.setdefault((r.source_record_type or '', int(r.source_order_id)), []).append(row)
        sku_by_po_id.setdefault(r.po_id, []).append(row)
    return sku_by_source, sku_by_po_id


def _rollup_sku_rows(sku_rows: list) -> tuple[float, float]:
    """把某来源的逐 SKU 快照汇总为订单级 (下单数量, 备品数量)。

    口径（RC-2 修正）：**先按产品名取 MAX（同 SKU 拆多供应商去重，与既有订单级
    去重口径一致），再对各产品求和** —— 得到「该订单自己的」数量，而不是
    ``MAX(product_quantity)``（后者在一张采购单覆盖多张订单时会系统性高估）。
    """
    per_product: dict[str, float] = {}
    per_product_spare: dict[str, float] = {}
    for row in sku_rows:
        key = _norm_name(row.product_name)
        per_product[key] = max(per_product.get(key, 0.0), float(row.order_qty or 0))
        per_product_spare[key] = max(per_product_spare.get(key, 0.0), float(row.spare_qty or 0))
    return sum(per_product.values()), sum(per_product_spare.values())


def _inject_per_sku_fields(record: dict, sku_rows: list) -> None:
    """为 ``items[]`` 的每个 SKU 注入逐 SKU 维度字段（方案 C）。

    - ``purchase_order_qty`` / ``spare_quantity``：该 SKU 维度的实际值（同 SKU
      拆多供应商时取 MAX）；``is_ordered`` 为该 SKU 维度；``per_sku_source`` 标识
      数据来源（``'po_sku'`` 逐 SKU 快照 / ``'order_level'`` 降级）。

    契约：未命中逐 SKU 快照时上述两字段显式置 ``None``（**不得**回填订单级标量、
    不得编造 0）；``is_ordered`` 回退为订单级 ``is_ordered``。消费方必须做 null 安全
    处理（前端 ``skuOrderQty`` / ``skuProductionQty`` 均带 ``!= null`` 守卫）。
    """
    ordered = record.get('is_ordered') is True
    for item in record.get('items', []) or []:
        target = _norm_name(item.get('product_name'))
        matched = [r for r in sku_rows if _norm_name(r.product_name) == target]
        if matched:
            item['purchase_order_qty'] = max(float(r.order_qty or 0) for r in matched)
            item['spare_quantity'] = max(float(r.spare_qty or 0) for r in matched)
            item['is_ordered'] = True
            item['per_sku_source'] = 'po_sku'
        else:
            # 逐 SKU 行不可得（未迁移 / 历史未回填 / 该 SKU 未被采购单覆盖）→ 降级
            item['purchase_order_qty'] = None
            item['spare_quantity'] = None
            item['is_ordered'] = ordered
            item['per_sku_source'] = 'order_level'


def _apply_ordered_fields(
    record: dict, pos: list, sku_rows: list | None = None, pos_exact: bool = True,
    search_qty_items: list[dict] | None = None,
) -> dict:
    """把「是否已下单 / 下单数量 / 备品」注入 beile 行，并逐 SKU 展开（方案 C）。

    数量口径契约（D-R2-1 / D-R2-2 修正后）：

    - ``pos_exact=True``（**order 路径恒定**；备货路径仅在有精确逐 SKU 行时）：
      订单级数量优先取「**该来源自己的**逐 SKU 行汇总」（按产品名 MAX 再求和，见
      :func:`_rollup_sku_rows`），修掉 RC-2「一张采购单覆盖 N 张订单时每单都显示同一
      合计」的系统性高估；逐 SKU 行不可得（未迁移 / 历史未回填 / 覆盖不完整）时
      **回退订单级** ``MAX(product_quantity)``；未下单时
      ``purchase_order_qty = record['quantity']``。此分支为既有口径，**不得改动**。
    - ``pos_exact=False``（备货**模糊**匹配路径）：模糊的 ``(customer, product_name)``
      匹配**只决定 `is_ordered` 信号，绝不决定数量**——为避免把模糊命中集合里的
      ``MAX(product_quantity)`` 当成该备货自己的数量（编造数字），
      ``purchase_order_qty`` / ``spare_quantity`` 一律置 ``None``。
      ``spare_rate`` 仍取模糊命中的 max，**仅作展示提示**（不代表该备货的准确损耗率）。
    - ``search_qty_items is not None``（**搜索态**，product_kw 命中、items 已收窄为
      命中 SKU 集合）：数量只统计**命中的 SKU**，绝不允许落到全单口径——
      已下单有逐 SKU 快照（caller 已预过滤为命中集合）→ rollup；
      无快照 → 置 ``None``（不把全单 ``MAX(product_quantity)`` 编造成命中集合的
      数量，D-R2-1 同源；前端回退命中 items 求和 / 生产数量显示「—」）；
      未下单 → 命中 items 的客户订单量之和。

    任何分支都不得抛错。
    """
    sku_rows = sku_rows or []
    covered_po_ids = {r.po_id for r in sku_rows}
    po_ids = {p.id for p in pos}
    # 覆盖完整性：该来源的每张关联采购单都必须有逐 SKU 快照，否则汇总不完整 → 回退 MAX
    rollup_ok = bool(sku_rows) and bool(po_ids) and covered_po_ids >= po_ids

    if pos:
        rates = [float(p.spare_rate) for p in pos if p.spare_rate is not None]
        record['spare_rate'] = max(rates) if rates else None
        record['is_ordered'] = True
        if not pos_exact:
            # 模糊来源不得产出数量（见 docstring 契约）——仅保留 is_ordered 信号
            record['purchase_order_qty'] = None
            record['spare_quantity'] = None
        elif search_qty_items is not None:
            # 搜索态：只统计命中 SKU 集合（sku_rows 已被 caller 预过滤为命中集合）
            if sku_rows:
                total_qty, total_spare = _rollup_sku_rows(sku_rows)
                record['purchase_order_qty'] = total_qty
                record['spare_quantity'] = total_spare
            else:
                record['purchase_order_qty'] = None
                record['spare_quantity'] = None
        elif rollup_ok:
            total_qty, total_spare = _rollup_sku_rows(sku_rows)
            record['purchase_order_qty'] = total_qty
            record['spare_quantity'] = total_spare
        else:
            record['purchase_order_qty'] = max((float(p.product_quantity or 0) for p in pos), default=0)
            record['spare_quantity'] = max((float(p.spare_quantity or 0) for p in pos), default=0)
    else:
        record['purchase_order_qty'] = (
            sum(float(it.get('quantity') or 0) for it in search_qty_items)
            if search_qty_items is not None else (record.get('quantity') or 0)
        )
        record['spare_quantity'] = 0
        record['spare_rate'] = None
        record['is_ordered'] = False

    _inject_per_sku_fields(record, sku_rows)
    return record


@cache_result(
    key_prefix="orders:beile:unconfirmed_count",
    ttl=60,
    local_ttl=0,
    key_builder=lambda *args, **kwargs: f"f{kwargs.get('factory', '')}",
)
async def get_beile_unconfirmed_count(db: AsyncSession, factory: str = '湖北') -> int:
    """未确认湖北记录总数（订单+备货）。

    全局统计量，与列表筛选/分页无关（顶部横幅使用），单独缓存：
    避免随列表查询键（页码/客户/关键字/确认状态）的每个变体重算。

    local_ttl=0：禁用 L1，仅走 L2。生产为多 worker（UVICORN_WORKERS=8）且
    `CACHE_L1_BROADCAST_ENABLED` 关闭，L1 无法跨 worker 失效；禁用 L1 后，
    采购侧 `invalidate_cache('orders:beile:*')` 删除 L2 键即可让所有 worker 立即回源，
    满足 AC-10「写入即失效 ≤1s」。代价仅每次请求一次本地 Redis GET。
    """
    unconfirmed_orders_result = await db.execute(
        select(func.count(Order.id)).where(
            Order.is_deleted.isnot(True),
            Order.confirmed_at.is_(None),
            Order.items.any(OrderItem.product.has(Product.factory == factory)),
        )
    )
    unconfirmed_stockins_result = await db.execute(
        select(func.count(StockIn.id)).where(
            StockIn.confirmed_at.is_(None),
            StockIn.product.has(Product.factory == factory),
        )
    )
    return (unconfirmed_orders_result.scalar() or 0) + (unconfirmed_stockins_result.scalar() or 0)


@cache_result(
    key_prefix="orders:beile:list",
    ttl=60,
    local_ttl=0,
    key_builder=lambda *args, **kwargs: f"p{kwargs.get('page', 1)}:pp{kwargs.get('per_page', 50)}:c{kwargs.get('customer', '')}:f{kwargs.get('factory', '')}:cs{kwargs.get('confirm_status', '')}:pk{kwargs.get('product_kw', '')}",
)
async def get_beile_orders_with_stockins(
    db: AsyncSession, *, page: int = 1, per_page: int = 50,
    customer: str | None = None, factory: str = '湖北',
    confirm_status: str | None = None,
    product_kw: str | None = None,
) -> dict:
    """获取湖北工厂订单+备货合并列表。

    通过 UNION ALL 合并查询 Order（订单）和 StockIn（备货），
    按产品工厂筛选，确保订单和备货记录都能在同一列表中展示。

    湖北确认流程筛选（订单与备货对齐，均按各自表的 confirmed_at 过滤）：
    - confirm_status='unconfirmed'：仅返回 confirmed_at IS NULL 的订单+备货
    - confirm_status='confirmed'：仅返回已确认（confirmed_at 非空）的订单+备货
    - 其他取值（含 None）不生效，返回完整订单+备货列表

    每行额外注入 `purchase_order_qty` / `spare_quantity` / `spare_rate` / `is_ordered`
    （口径见 `_apply_ordered_fields`）：
    - 订单行：由 `source_order_ids` **精确**匹配，数量取「该订单自身逐 SKU 之和」，
      回退 `MAX(product_quantity)`；
    - 备货行：优先按 `purchase_order_sku.source_record_type='stockin'` **精确**匹配并取
      逐 SKU 汇总；无精确逐 SKU 行时，`(customer, product_name)` **模糊**匹配只决定
      `is_ordered` 信号，数量置 `None`（**不得**把模糊命中的 `MAX(product_quantity)`
      当成该备货数量 —— D-R2-1/2）。

    local_ttl=0：禁用 L1 以支持多 worker 下「写入即失效」（见 get_beile_unconfirmed_count）。

    参考 purchase_order_query.get_unprocessed_orders 的实现方案。
    """
    confirmed: bool | None = None
    if confirm_status == 'unconfirmed':
        confirmed = False
    elif confirm_status == 'confirmed':
        confirmed = True

    unified = _build_beile_unified_query(confirmed, customer, factory, product_kw)

    # ---- 1. 未确认湖北记录总数（全局量，独立缓存） ----
    unconfirmed_count = await get_beile_unconfirmed_count(db, factory)

    # ---- 2. completed 采购单映射（一次查询，供行级注入，无 N+1） ----
    by_order_id, by_customer_product, po_by_id = await _fetch_completed_po_maps(db)

    # ---- 2b. 逐 SKU 快照映射（方案 C；表缺失时优雅降级为空映射） ----
    sku_by_source, _sku_by_po = await _fetch_po_sku_maps(db)

    # ---- 3. 分页查询当前页（窗口列一并取 total，UNION 只执行一次） ----
    offset = (page - 1) * per_page
    page_result = await db.execute(
        select(
            unified.c.record_type,
            unified.c.source_id,
            unified.c.order_no,
            unified.c.customer,
            unified.c.sort_date,
            func.count().over().label('total_count'),
        )
        # 次级排序键保证同秒记录的跨页顺序稳定，避免翻页丢行/重行
        .order_by(desc(unified.c.sort_date).nullslast(), unified.c.record_type, unified.c.source_id)
        .limit(per_page)
        .offset(offset)
    )
    rows = page_result.all()

    if not rows:
        # offset=0 且无行 → 确实无数据；页码越界时窗口列不在本页结果中，
        # 用 LIMIT 1 的窗口 count 探测总数（避免为回退再完整执行一遍 UNION COUNT）
        if offset == 0:
            total = 0
        else:
            probe = await db.execute(
                select(func.count().over().label('total_count')).select_from(unified).limit(1)
            )
            total = probe.scalar() or 0
        return {'items': [], 'total': total, 'page': page, 'per_page': per_page,
                'unconfirmed_count': unconfirmed_count}

    total = rows[0].total_count or 0

    # ---- 4. 按来源批量查询完整数据 ----
    order_ids = [r.source_id for r in rows if r.record_type == 'order']
    stockin_ids = [r.source_id for r in rows if r.record_type == 'stockin']

    orders_map, stockins_map = await _fetch_beile_records_by_ids(db, order_ids, stockin_ids)

    # ---- 5. 构建 records（保持 SQL 排序顺序）----
    items: list[dict] = []
    for r in rows:
        if r.record_type == 'order':
            o = orders_map.get(r.source_id)
            if o:
                items.append(_build_beile_order_record(
                    o, factory, by_order_id.get(o.id, []), sku_by_source.get(('order', o.id), []),
                    product_kw=product_kw,
                ))
        else:
            s = stockins_map.get(r.source_id)
            if s:
                stockin_product = s.product.name if s.product else None
                # 精确（带类型）匹配：以该备货自身为 source 的逐 SKU 快照
                # （source_record_type='stockin' AND source_order_id=stockin.id）。
                exact_rows = sku_by_source.get(('stockin', s.id), [])
                if exact_rows:
                    # 按去重后的 po_id 取采购单行（保持 SQL 稳定顺序）
                    seen_po_ids: set[int] = set()
                    ordered_po_ids: list[int] = []
                    for sku_row in exact_rows:
                        if sku_row.po_id in po_by_id and sku_row.po_id not in seen_po_ids:
                            seen_po_ids.add(sku_row.po_id)
                            ordered_po_ids.append(sku_row.po_id)
                    pos = [po_by_id[pid] for pid in ordered_po_ids]
                    pos_exact = True
                else:
                    # 无精确逐 SKU 行 → 保留模糊匹配以维持「已下单」信号，
                    # 但 pos_exact=False 使数量一律为 None（禁止把 MAX(product_quantity) 当数量）
                    pos = by_customer_product.get((s.customer or '', stockin_product or ''), [])
                    pos_exact = False
                items.append(_build_beile_stockin_record(
                    s, factory, pos, exact_rows, pos_exact=pos_exact,
                ))

    return {'items': items, 'total': total, 'page': page, 'per_page': per_page,
            'unconfirmed_count': unconfirmed_count}


def _build_beile_order_record(
    order: Order, factory: str, pos: list, sku_rows: list | None = None,
    product_kw: str | None = None,
) -> dict:
    """构建湖北订单列表中的订单记录（含多 SKU）。

    `pos` 为该客户订单关联的 completed 采购单行集合（source_order_ids 精确匹配）。
    `sku_rows` 为该订单的逐 SKU 快照行（方案 C；缺省时降级为订单级口径）。

    ``product_kw``（搜索态，SKU 级搜索语义）：SQL 侧「任一 SKU 命中即整单返回」，
    此处在行构建时把 ``items`` 收窄为**命中的 SKU**，并同步预过滤 ``sku_rows``，
    使订单级数量（purchase_order_qty / spare_quantity / items 求和回退）都只统计
    命中集合——列表的「订单数量 / 生产数量」即「搜索到的 SKU 的数量」，
    不再显示整个订单的总数量。产品名称列直接读收窄后的 items。

    **工厂收窄（生产 BUG 2026-10-15，PO-20261015-2584）**：SQL 按「任一本厂 SKU 命中
    即整单入选」（``Order.items.any(...)``），行构建若不收窄，同单里的**他厂 SKU**
    （如东莞）会泄漏进湖北列表（页面/详情/导出/打印同源）。故 source_items 先按
    ``item.product.factory == factory`` 收窄，与 SQL 入选语义对齐；无 product 关联的
    历史行（factory 不可判）保留（与 SQL ``Product.factory == factory`` 的
    ``has()`` 隐式 INNER JOIN 语义一致：无 product 即不入选，但历史兼容列行仍在）。
    """
    # 工厂收窄：只保留本厂 SKU（item.product 为 None 的历史行保留，不误杀）
    factory_items = [
        it for it in (order.items or [])
        if it.product is None or it.product.factory == factory
    ]
    # 防御：全部 SKU 都无工厂归属且过滤为空时回退全量，绝不出「空 items 订单」
    if not factory_items:
        factory_items = list(order.items or [])

    matched_items: list[OrderItem] | None = None
    kwl = (product_kw or '').strip().casefold()
    if kwl:
        cand = [
            it for it in factory_items
            if kwl in _norm_name(it.product_name) or kwl in _norm_name(it.product_barcode)
        ]
        # 防御：SQL 已保证整单至少一个 SKU 命中；Python 侧因转义/时序差异过滤为空时
        # 回退工厂收窄结果，绝不出「空 items 订单」（空单会把合计行清零）
        matched_items = cand if cand else list(factory_items)
    source_items = matched_items if matched_items is not None else factory_items

    items_data = [
        {
            'id': item.id,
            'product_id': item.product_id,
            'product_name': item.product_name,
            'product_barcode': item.product_barcode,
            'product_image': item.product.image or '' if item.product else '',
            'quantity': item.quantity,
            'deduct_quantity': item.deduct_quantity or 0,
            'note': item.note or '',
        }
        for item in source_items
    ]
    first_item = source_items[0] if source_items else None
    record = {
        'id': order.id,
        'order_no': order.order_no,
        'customer': order.customer,
        'product_id': first_item.product_id if first_item else None,
        'product_name': first_item.product_name if first_item else None,
        'quantity': first_item.quantity if first_item else 0,
        'order_date': _fmt_beile_time(order.order_date),
        'record_type': 'order',
        'items': items_data,
        'factories': [factory],
        # 湖北订单确认状态：confirmed_at IS NULL 视为「未确认订单」
        'confirmed': order.confirmed_at is not None,
        'confirmed_at': _fmt_beile_time(order.confirmed_at),
        'confirmed_by': order.confirmed_by.username if order.confirmed_by else None,
    }
    if matched_items is not None:
        # 搜索态：逐 SKU 快照同步收窄为命中集合，数量口径随之只统计命中 SKU
        matched_names = {_norm_name(i.product_name) for i in matched_items}
        sku_rows = [r for r in (sku_rows or []) if _norm_name(r.product_name) in matched_names]
        return _apply_ordered_fields(record, pos, sku_rows, search_qty_items=items_data)
    return _apply_ordered_fields(record, pos, sku_rows)


def _build_beile_stockin_record(
    stockin: StockIn, factory: str, pos: list, sku_rows: list | None = None,
    pos_exact: bool = True,
) -> dict:
    """构建湖北订单列表中的备货记录。

    `pos`：
      - `pos_exact=True`  → 以该备货自身为来源（`source_record_type='stockin'`）的
        精确逐 SKU 快照所属的 completed 采购单行集合；
      - `pos_exact=False` → 按 (customer, product_name) **模糊**匹配到的 completed
        采购单行集合（PRD Q2）；此时仅用于确定「已下单」信号，**不产出数量**。
    `sku_rows` 为该备货的逐 SKU 快照行（方案 C；缺省时降级为订单级口径）。
    `pos_exact` 直接透传给 :func:`_apply_ordered_fields`，见其数量口径契约。
    """
    product_name = stockin.product.name if stockin.product else None
    product_barcode = stockin.product.barcode if stockin.product else None
    product_image = stockin.product.image or '' if stockin.product else ''
    items_data = [{
        'id': stockin.id,
        'product_id': stockin.product_id,
        'product_name': product_name,
        'product_barcode': product_barcode,
        'product_image': product_image,
        'quantity': stockin.quantity,
        'deduct_quantity': 0,
        'note': stockin.note or '',
    }]
    record = {
        'id': stockin.id,
        'order_no': stockin.stockin_no,
        'customer': stockin.customer,
        'product_id': stockin.product_id,
        'product_name': product_name,
        'quantity': stockin.quantity,
        'order_date': _fmt_beile_time(stockin.stockin_date),
        'record_type': 'stockin',
        'items': items_data,
        'factories': [factory],
        # 湖北备货确认状态（与订单确认流程对齐）：confirmed_at IS NULL 视为「未确认备货」
        'confirmed': stockin.confirmed_at is not None,
        'confirmed_at': _fmt_beile_time(stockin.confirmed_at),
        'confirmed_by': stockin.confirmed_by.username if stockin.confirmed_by else None,
    }
    return _apply_ordered_fields(record, pos, sku_rows, pos_exact=pos_exact)


async def _order_has_completed_po(db: AsyncSession, order_id: int) -> bool:
    """该客户订单是否已存在 completed 关联采购单（source_order_ids 精确元素匹配，非 LIKE）。"""
    source_ids_list = (await db.execute(
        select(PurchaseOrder.source_order_ids).where(
            PurchaseOrder.status == PurchaseOrderStatus.COMPLETED
        )
    )).scalars().all()
    return any(order_id in parse_source_order_ids(s) for s in source_ids_list)


async def _stockin_has_completed_po(db: AsyncSession, customer: str | None, product_name: str | None) -> bool:
    """该备货是否已存在 (customer, product_name) 匹配的 completed 采购单（近似匹配）。"""
    rows = (await db.execute(
        select(PurchaseOrder.customer_name, PurchaseOrder.product_name).where(
            PurchaseOrder.status == PurchaseOrderStatus.COMPLETED
        )
    )).all()
    target = (customer or '', product_name or '')
    return any((r.customer_name or '', r.product_name or '') == target for r in rows)


async def confirm_beile_order(db: AsyncSession, order_id: int, current_user: User) -> dict:
    """确认湖北订单（beile-order 页面）。

    业务规则：
    - 仅允许确认 factory=湖北 的订单，与其他地区（东莞等）订单独立隔离：
      非湖北工厂订单通过本接口一律返回 404，防止跨区域串改。
    - 顺序（CR-1 明确）：查记录 → 不存在 404 → **已确认 → 幂等成功 200** →
      未确认 → 门控（未下单 → `ConflictError` 409）→ 写入。
      「幂等早退」必须在门控**之前**：门控的目的是防止误确认**尚未下单且尚未确认**
      的记录；对**已确认**的历史记录既无动作也无风险，若被门控拦成 409 即为行为回退。
    - 门控：未确认 且 未在采购中心完成下单（无 completed 关联采购单）时抛
      `ConflictError`（409），文案 `BEILE_NOT_ORDERED_DETAIL`（PRD P0-4 / AC-5）。
    - 幂等：订单已确认时直接返回成功（`already_confirmed=True`），不重复记录确认人。
    - 只写入 confirmed_at / confirmed_by_id，不影响 order.status
      （派生状态机不受确认流程干扰）。
    """
    result = await db.execute(
        select(Order)
        .where(
            Order.id == order_id,
            Order.is_deleted.isnot(True),
            Order.items.any(OrderItem.product.has(Product.factory == '湖北')),
        )
        .with_for_update()
    )
    order = result.scalar_one_or_none()
    if not order:
        raise NotFoundError('订单不存在或非湖北工厂订单')

    # CR-1：幂等早退必须在门控之前（已确认记录不再过未下单门控，避免 200 回退为 409）
    if order.confirmed_at is not None:
        logger.info('湖北订单重复确认（幂等）：order_id=%s，操作人：%s', order_id, current_user.username)
        return {'success': True, 'message': '订单已确认', 'already_confirmed': True}

    # 门控：未在采购中心完成下单则拒绝确认（交全局 handler 转 409）
    if not await _order_has_completed_po(db, order.id):
        logger.info('湖北订单确认被拒（未下单）：order_no=%s，操作人：%s', order.order_no, current_user.username)
        raise ConflictError(BEILE_NOT_ORDERED_DETAIL)

    order.confirmed_at = datetime.now(UTC).replace(tzinfo=None)  # naive UTC: DB列类型为 TIMESTAMP WITHOUT TIME ZONE
    order.confirmed_by_id = current_user.id
    await db.flush()

    # 该订单的「未确认提醒」通知标记为已读，确认后不再残留未读待办
    await db.execute(
        update(Notification)
        .where(
            Notification.related_order_id == order.id,
            Notification.type == BEILE_UNCONFIRMED_TYPE,
            Notification.is_read.is_(False),
        )
        .values(is_read=True)
    )

    # 缓存失效由 endpoint 层在事务提交后执行（避免并发请求用未提交前数据回填缓存）

    logger.info('湖北订单确认成功：order_no=%s，操作人：%s', order.order_no, current_user.username)
    return {'success': True, 'message': '订单已确认', 'already_confirmed': False}


async def confirm_beile_stockin(db: AsyncSession, stockin_id: int, current_user: User) -> dict:
    """确认湖北备货（beile-order 页面，与订单确认流程对齐）。

    业务规则：
    - 仅允许确认 factory=湖北 的备货记录，与其他地区独立隔离：
      非湖北工厂备货通过本接口一律返回 404，防止跨区域串改。
    - 顺序（CR-1 明确）：查记录 → 不存在 404 → **已确认 → 幂等成功 200** →
      未确认 → 门控（未下单 → `ConflictError` 409）→ 写入。
      「幂等早退」必须在门控**之前**（理由同 `confirm_beile_order`）。
    - 门控：未确认 且 无 (customer, product_name) 匹配的 completed 采购单时抛
      `ConflictError`（409）（PRD P0-4 / AC-9）。
    - 幂等：备货已确认时直接返回成功（`already_confirmed=True`），不重复记录确认人。
    - 只写入 confirmed_at / confirmed_by_id，不影响库存业务数据。
    """
    result = await db.execute(
        select(StockIn)
        .options(selectinload(StockIn.product))
        .where(
            StockIn.id == stockin_id,
            StockIn.product.has(Product.factory == '湖北'),
        )
        .with_for_update()
    )
    stockin = result.scalar_one_or_none()
    if not stockin:
        raise NotFoundError('备货记录不存在或非湖北工厂备货')

    # CR-1：幂等早退必须在门控之前（已确认记录不再过未下单门控，避免 200 回退为 409）
    if stockin.confirmed_at is not None:
        logger.info('湖北备货重复确认（幂等）：stockin_id=%s，操作人：%s', stockin_id, current_user.username)
        return {'success': True, 'message': '备货已确认', 'already_confirmed': True}

    # 门控：无匹配 completed 采购单则拒绝确认
    product_name = stockin.product.name if stockin.product else None
    if not await _stockin_has_completed_po(db, stockin.customer, product_name):
        logger.info('湖北备货确认被拒（未下单）：stockin_no=%s，操作人：%s', stockin.stockin_no, current_user.username)
        raise ConflictError(BEILE_NOT_ORDERED_DETAIL)

    stockin.confirmed_at = datetime.now(UTC).replace(tzinfo=None)  # naive UTC: DB列类型为 TIMESTAMP WITHOUT TIME ZONE
    stockin.confirmed_by_id = current_user.id
    await db.flush()

    # 缓存失效由 endpoint 层在事务提交后执行（避免并发请求用未提交前数据回填缓存）

    logger.info('湖北备货确认成功：stockin_no=%s，操作人：%s', stockin.stockin_no, current_user.username)
    return {'success': True, 'message': '备货已确认', 'already_confirmed': False}
