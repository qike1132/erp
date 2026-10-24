"""
库存查询业务逻辑（列表 / 库存聚合 / 统计）

包含入库/出库/退货列表查询（get_stockins/get_stockouts/get_stockreturns）、
库存聚合查询（get_inventory/get_inventory_paginated）及其 SQL 聚合辅助函数、
库存统计（get_stock_overview_stats）。
「库存」列（结余 = 包装部入库 − 已出货）已并入 get_inventory_paginated 的 CTE。

模块级 SQL 片段常量（_SI_PID/_SO_CUST 等）仅在此处使用，随函数一并迁移至此。
"""
import hashlib
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import ColumnElement, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from sqlalchemy.sql.elements import TextClause

from fastapi_app.core.business_time import _BUSINESS_TZ, fmt_business
from fastapi_app.core.cache import cache_result
from fastapi_app.core.sanitizer import escape_like
from fastapi_app.shared_models import (
    DailyProductionRecord,
    InventoryLog,
    Order,
    OrderItem,
    Product,
    StockIn,
    StockOut,
    StockReturn,
)


def _day_range_utc(day_str: str, *, end: bool = False) -> datetime:
    """YYYY-MM-DD → 该北京日历日的起/止边界（aware UTC）。

    2026-10-17 审计 F-BE-SVC-STOCK-06：原先把北京日历日 ``.replace(tzinfo=UTC)``
    锚定成 UTC 零点，东八区窗口整体偏 8 小时（当天 00:00–07:59 的记录落到前一天）。
    与 stock_out_service._resolve_stockout_datetime / order_batch_create 同口径。
    """
    d = datetime.strptime(day_str, '%Y-%m-%d')
    if end:
        d = d.replace(hour=23, minute=59, second=59)
    return d.replace(tzinfo=_BUSINESS_TZ).astimezone(UTC)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQL 条件片段常量（安全边界说明）
#
# 以下常量均为硬编码 SQL 片段，不包含任何用户输入。用户提供的筛选值
# （客户名、产品ID列表）一律通过 SQLAlchemy 绑定参数 :sc / :pids 传递，
# 不直接拼入 SQL 字符串。将这些片段提取为常量是为了：
#   1. 避免在多处重复书写相同字符串，降低拼写不一致风险；
#   2. 明确标识"此处为受控的静态 SQL 片段"，便于安全审查；
#   3. 防止未来修改时误将动态值拼入条件字符串。
# 任何新增条件片段都必须遵循同一规则：片段本身为字面量，值走绑定参数。
# ---------------------------------------------------------------------------
# 客户筛选条件（值通过 :sc 绑定）
_CUST_CLAUSE = ' AND customer = :sc'
_SI_CUST = ' AND si.customer = :sc'
_SO_CUST = ' AND so.customer = :sc'
_O_CUST = ' AND o.customer = :sc'
# 产品ID筛选条件（值通过 :pids 绑定，pids 为元组）
_PID_CLAUSE = ' AND product_id = ANY(:pids)'
_SI_PID = ' AND si.product_id = ANY(:pids)'
_SO_PID = ' AND so.product_id = ANY(:pids)'
_O_PID = ' AND o.product_id = ANY(:pids)'
_PROD_PID = ' AND product_id = ANY(:pids)'
# 多 SKU 订单聚合：明细优先，无明细（批量导入路径的兼容订单）回退订单级字段
_OI_PID = ' AND oi.product_id = ANY(:pids)'
_OI_OR_O_PID = ' AND (oi.product_id = ANY(:pids) OR (oi.id IS NULL AND o.product_id = ANY(:pids)))'

# 软删除订单不得计入库存/国家聚合：删除订单只置 is_deleted=TRUE，不物理删除行；
# 缺此过滤会让已删订单的数量永久留在 /stock 视图（与 _get_all_customers、
# get_stock_overview_stats 的口径保持一致）。
_O_NOT_DELETED = ' AND o.is_deleted IS NOT TRUE'


def _factory_match(factory: str):
    """读侧工厂条件：本厂产品 + 未分配工厂的历史行（与写侧 factory_scope 放行口径一致）。"""
    return or_(Product.factory == factory, Product.factory.is_(None), Product.factory == '')


@cache_result(
    key_prefix='stockins:list',
    ttl=30,
    local_ttl=10,
    key_builder=lambda *args, **kwargs: f"pg:{kwargs.get('page',1)}:pp:{kwargs.get('per_page',50)}:c:{kwargs.get('customer','') or ''}:sd:{kwargs.get('start_date','') or ''}:ed:{kwargs.get('end_date','') or ''}:f:{kwargs.get('factory','') or ''}",
)
async def get_stockins(db: AsyncSession, page: int=1, per_page: int=50,
                       customer: str | None = None,
                       start_date: str | None = None, end_date: str | None = None,
                       factory: str | None = None) -> dict:
    """获取入库列表（含关联数据，支持分页和筛选）- SQL子查询优化版"""
    conditions: list[ColumnElement[bool]] = []
    if customer:
        conditions.append(StockIn.customer.like(f'%{escape_like(customer)}%'))
    if start_date:
        try:
            sd = _day_range_utc(start_date)
            conditions.append(StockIn.stockin_date >= sd)
        except ValueError:
            pass  # defensive: 可选 ValueError 静默处理,不影响主流程
    if end_date:
        try:
            ed = _day_range_utc(end_date, end=True)
            conditions.append(StockIn.stockin_date <= ed)
        except ValueError:
            pass  # defensive: 可选 ValueError 静默处理,不影响主流程

    base_where = select(StockIn.id)
    if factory:
        # 工厂隔离（P0-2）：厂绑定用户只能看本厂产品的备货记录。
        base_where = base_where.join(Product, Product.id == StockIn.product_id).where(_factory_match(factory))
    for condition in conditions:
        base_where = base_where.where(condition)

    total = (await db.execute(select(func.count()).select_from(base_where.subquery()))).scalar() or 0
    id_result = await db.execute(
        base_where
        .order_by(StockIn.stockin_date.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    page_ids = [row[0] for row in id_result.all()]
    if not page_ids:
        return {'items': [], 'total': total, 'page': page, 'per_page': per_page}
    deducted_sub = (
        select(
            StockOut.stockin_id.label('sid'),
            func.coalesce(func.sum(StockOut.quantity - StockOut.returned_quantity), 0).label('deducted')
        )
        .where(StockOut.stockin_id.isnot(None))
        .group_by(StockOut.stockin_id)
        .subquery()
    )
    result = await db.execute(
        select(StockIn, func.coalesce(deducted_sub.c.deducted, 0).label('deducted'))
        .outerjoin(deducted_sub, StockIn.id == deducted_sub.c.sid)
        .options(joinedload(StockIn.product))
        .where(StockIn.id.in_(page_ids))
        .order_by(StockIn.stockin_date.desc())
    )
    data = []
    for row in result.all():
        stock_in = row.StockIn
        deducted = int(row.deducted) if row.deducted is not None else 0
        data.append({
            'id': stock_in.id, 'stockin_no': stock_in.stockin_no,
            'stockin_date': fmt_business(stock_in.stockin_date, '%Y-%m-%d') if stock_in.stockin_date else '',
            'customer': stock_in.customer,
            'product': {'id': stock_in.product.id, 'name': stock_in.product.name, 'barcode': stock_in.product.barcode or '', 'image': stock_in.product.image or ''} if stock_in.product else None,
            'quantity': stock_in.quantity,
            'deducted': deducted,
            'note': stock_in.note or '',
        })
    return {'items': data, 'total': total, 'page': page, 'per_page': per_page}


@cache_result(
    key_prefix='stockouts:list',
    ttl=30,
    local_ttl=10,
    key_builder=lambda *args, **kwargs: f"pg:{kwargs.get('page',1)}:pp:{kwargs.get('per_page',50)}:c:{kwargs.get('customer','') or ''}:sd:{kwargs.get('start_date','') or ''}:ed:{kwargs.get('end_date','') or ''}:f:{kwargs.get('factory','') or ''}",
)
async def get_stockouts(db: AsyncSession, page: int=1, per_page: int=50,
                        customer: str | None = None,
                        start_date: str | None = None, end_date: str | None = None,
                        factory: str | None = None) -> dict:
    """获取出库列表（仅独立出库，非抵扣，支持分页和筛选）

    筛选维度：customer（模糊匹配）、start_date/end_date（按 stockout_date 过滤）。
    """
    from fastapi_app.shared_models import Order

    conditions: list[ColumnElement[bool]] = [StockOut.stockin_id.is_(None)]
    if customer:
        conditions.append(StockOut.customer.like(f'%{escape_like(customer)}%'))
    if start_date:
        try:
            sd = _day_range_utc(start_date)
            conditions.append(StockOut.stockout_date >= sd)
        except ValueError:
            pass  # defensive: 可选 ValueError 静默处理,不影响主流程
    if end_date:
        try:
            ed = _day_range_utc(end_date, end=True)
            conditions.append(StockOut.stockout_date <= ed)
        except ValueError:
            pass  # defensive: 可选 ValueError 静默处理,不影响主流程

    # 先用子查询过滤 + 分页取 ID，再按 ID 批量加载关联数据，避免 joinedload 与过滤 JOIN 冲突
    id_query = select(StockOut.id).where(*conditions)
    if factory:
        # 工厂隔离（P0-2）：厂绑定用户只能看本厂产品的出货记录。
        id_query = id_query.join(Product, Product.id == StockOut.product_id).where(_factory_match(factory))

    total = (await db.execute(select(func.count()).select_from(id_query.subquery()))).scalar() or 0

    id_result = await db.execute(
        id_query.order_by(StockOut.stockout_date.desc()).offset((page - 1) * per_page).limit(per_page)
    )
    page_ids = [row[0] for row in id_result.all()]
    if not page_ids:
        return {'items': [], 'total': total, 'page': page, 'per_page': per_page}

    result = await db.execute(
        select(StockOut)
        .options(
            joinedload(StockOut.product),
            joinedload(StockOut.order).selectinload(Order.items),
        )
        .where(StockOut.id.in_(page_ids))
        .order_by(StockOut.stockout_date.desc())
    )
    stockouts = result.scalars().unique().all()
    data = []
    for stock_out in stockouts:
        item = {
            'id': stock_out.id,
            'stockout_no': stock_out.stockout_no,
            'stockout_date': fmt_business(stock_out.stockout_date, '%Y-%m-%d') if stock_out.stockout_date else '',
            'customer': stock_out.customer,
            'product_id': stock_out.product_id,
            'product_name': stock_out.product.name if stock_out.product else '',
            'product_image': stock_out.product.image if stock_out.product else '',
            'barcode': stock_out.product.barcode if stock_out.product else '',
            'product': {'id': stock_out.product.id, 'name': stock_out.product.name, 'barcode': stock_out.product.barcode or '', 'image': stock_out.product.image or ''} if stock_out.product else None,
            'quantity': stock_out.quantity,
            'returned_quantity': stock_out.returned_quantity,
            'note': stock_out.note or '',
        }
        data.append(item)
    return {'items': data, 'total': total, 'page': page, 'per_page': per_page}


async def get_stockreturns(db: AsyncSession, stockout_id: int | None = None,
                           page: int = 1, per_page: int = 50,
                           customer: str | None = None,
                           start_date: str | None = None, end_date: str | None = None) -> dict:
    """获取退货列表（**仅 active**；支持按出货ID/客户/日期区间筛选，支持分页）

    只展示 active 行 —— 与退货流水报表口径一致（report_data_service 同样只查 active）。
    2026-10-09 起取消退货即删除该行，正常情况下不会再有 cancelled 行；此过滤是对
    历史遗留作废行的防御，且必须落在 SQL 里才能保证分页 ``total`` 正确。
    """
    # 构建共享过滤条件：stockout_id 为空时不加条件
    # （此前 `== stockout_id if stockout_id else True` 在无筛选时退化为 `== True` 恒假，导致 total 恒为 0）
    conditions = [StockReturn.status == 'active']
    if stockout_id:
        conditions.append(StockReturn.stockout_id == stockout_id)
    if customer:
        conditions.append(StockReturn.customer.like(f'%{escape_like(customer)}%'))
    if start_date:
        try:
            sd = _day_range_utc(start_date)
            conditions.append(StockReturn.return_date >= sd)
        except ValueError:
            pass  # defensive: 可选 ValueError 静默处理,不影响主流程
    if end_date:
        try:
            # 左闭右开：end_date 当天整天都计入（含 23:59:59.x 的微秒记录，
            # 退货时间由 business_now() 填充含微秒，23:59:59 口径会漏掉最后一秒内的单）
            ed = _day_range_utc(end_date, end=True) + timedelta(days=1)
            conditions.append(StockReturn.return_date < ed)
        except ValueError:
            pass  # defensive: 可选 ValueError 静默处理,不影响主流程
    total = (await db.execute(select(func.count(StockReturn.id)).where(*conditions))).scalar() or 0
    result = await db.execute(
        select(StockReturn)
        .where(*conditions)
        .options(joinedload(StockReturn.product), joinedload(StockReturn.stockout))
        .order_by(StockReturn.return_date.desc())
        .offset((page - 1) * per_page).limit(per_page)
    )
    returns = result.scalars().unique().all()
    data = []
    for stock_return in returns:
        data.append({
            'id': stock_return.id,
            'return_no': stock_return.return_no,
            'return_date': fmt_business(stock_return.return_date, '%Y-%m-%d') if stock_return.return_date else '',
            'product': {'id': stock_return.product.id, 'name': stock_return.product.name} if stock_return.product else None,
            'quantity': stock_return.quantity,
            'customer': stock_return.customer,
            'stockout_id': stock_return.stockout_id,
            'stockout_no': stock_return.stockout.stockout_no if stock_return.stockout else '',
            # 关联出货的批次号（该退货退的是哪个批次）；关联行缺失时为空串
            'batch_no': stock_return.stockout.batch_no or '' if stock_return.stockout else '',
            'reason': stock_return.reason or '',
            'note': stock_return.note or '',
            'status': stock_return.status,
        })
    return {'items': data, 'total': total, 'page': page, 'per_page': per_page}


def _parse_nos(raw: str, limit: int = 500) -> list[str]:
    """逗号切分单号并 trim/去空/去重/限量（报表聚合行还原用）。"""
    out: list[str] = []
    seen: set[str] = set()
    for part in (raw or '').split(','):
        s = part.strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
        if len(out) >= limit:
            break
    return out


async def get_stockout_records(db: AsyncSession, kind: str = 'stockout', nos: str = '', product: str = '',
                               factory: str | None = None) -> list[dict]:
    """按单号还原出货/抵扣明细行（报表聚合行 → 具体记录）。

    kind='stockout'：独立出货（stockin_id IS NULL），按 stockout_no 匹配。
    kind='deduction'：备货抵扣（stockin_id IS NOT NULL），按关联订单号 order_no 匹配。
    product 非空时按产品名收窄——同一订单可能对多个产品分别抵扣，仅凭 order_no 会
    还原出他产品的抵扣行（picker 里可能选错），故用行内产品名再收一道。
    返回行带 id / 单号 / 数量 / 已退量 / 客户 / 日期 / 备注 / 产品，供前端行内编辑与删除。
    """
    codes = _parse_nos(nos)
    if not codes:
        return []
    if kind == 'deduction':
        stmt = (
            select(StockOut)
            .join(Order, StockOut.order_id == Order.id)
            .where(StockOut.stockin_id.is_not(None), Order.order_no.in_(codes))
        )
    else:
        stmt = select(StockOut).where(StockOut.stockin_id.is_(None), StockOut.stockout_no.in_(codes))
    if product:
        # 子查询而非 join：避免与 joinedload(StockOut.product) 形成对 product 的二次 join
        stmt = stmt.where(StockOut.product_id.in_(select(Product.id).where(Product.name == product)))
    if factory:
        # 工厂隔离（P0-2）：按单号还原明细同样只能命中本厂产品。
        stmt = stmt.where(StockOut.product_id.in_(select(Product.id).where(_factory_match(factory))))
    result = await db.execute(
        stmt.options(joinedload(StockOut.product)).order_by(StockOut.stockout_date.desc(), StockOut.id.desc())
    )
    data = []
    for so in result.scalars().unique().all():
        data.append({
            'id': so.id,
            'stockout_no': so.stockout_no,
            'stockout_date': fmt_business(so.stockout_date, '%Y-%m-%d') if so.stockout_date else '',
            'customer': so.customer or '',
            'product_id': so.product_id,
            'product_name': so.product.name if so.product else '',
            'barcode': so.product.barcode if so.product else '',
            'quantity': so.quantity,
            'returned_quantity': so.returned_quantity,
            'batch_no': so.batch_no or '',
            'note': so.note or '',
            'stockin_id': so.stockin_id,
            'order_id': so.order_id,
        })
    return data


async def get_stockreturn_records(db: AsyncSession, nos: str = '') -> list[dict]:
    """按退货单号还原退货明细行（报表聚合行 → 具体记录）。仅 active。"""
    codes = _parse_nos(nos)
    if not codes:
        return []
    result = await db.execute(
        select(StockReturn)
        .where(StockReturn.status == 'active', StockReturn.return_no.in_(codes))
        .options(joinedload(StockReturn.product), joinedload(StockReturn.stockout))
        .order_by(StockReturn.return_date.desc(), StockReturn.id.desc())
    )
    data = []
    for sr in result.scalars().unique().all():
        data.append({
            'id': sr.id,
            'return_no': sr.return_no,
            'return_date': fmt_business(sr.return_date, '%Y-%m-%d') if sr.return_date else '',
            'customer': sr.customer or '',
            'product_id': sr.product_id,
            'product_name': sr.product.name if sr.product else '',
            'quantity': sr.quantity,
            'stockout_id': sr.stockout_id,
            'stockout_no': sr.stockout.stockout_no if sr.stockout else '',
            'reason': sr.reason or '',
            'note': sr.note or '',
        })
    return data


@cache_result(key_prefix='inventory', ttl=60, local_ttl=30, key_builder=lambda *args, **kwargs: f"c{kwargs.get('search_customer', '')}:p{kwargs.get('search_product', '')}")
async def get_inventory(db: AsyncSession, search_customer: str='', search_product: str='') -> dict:
    """全量库存视图（兼容入口）。

    Z03-R1：旧版 `_fetch_inventory` 三表 Python 合并实现已删除——它与
    `get_inventory_paginated` 的 CTE 口径已分叉（软删订单过滤/结余列）。本函数
    现在只是分页版的“取全量”薄包装，两处调用方共用同一查询内核。
    """
    result = await get_inventory_paginated(
        db, search_customer=search_customer, search_product=search_product,
        page=1, per_page=100_000,
    )
    return {
        'inventory_data': result['inventory_data'],
        'total_order_qty': result['total_order_qty'],
        'total_stockin_qty': result['total_stockin_qty'],
        'total_stock': result['total_stock'],
    }


@cache_result(key_prefix="inventory:paginated", ttl=120, local_ttl=60,
             key_builder=lambda **kwargs: f"{kwargs.get('search_customer','')}-{kwargs.get('search_product','')}-{kwargs.get('stock_status','')}-{kwargs.get('page',1)}-{kwargs.get('per_page',50)}-f:{kwargs.get('factory','') or ''}")
async def get_inventory_paginated(db: AsyncSession, search_customer: str = '', search_product: str = '',
                                  page: int = 1, per_page: int = 50,
                                  stock_status: str = '', factory: str = '') -> dict:
    """
    库存分页查询 - SQL CTE 优化版
    将4次聚合查询合并为单次 CTE 查询，在数据库层面完成合并、过滤和分页，
    避免加载全量数据到 Python 内存。20K+ 条数据时响应时间从秒级降至百毫秒级。

    stock_status（2026-10-17 审计 AUD-22）：zero=仅零库存行 / active=仅有库存行，
    空串=不过滤。此前移动端在截断后的首页数据上做本地过滤，跨页结果失真。
    """
    # 仅在有产品搜索时才加载产品ID列表；无搜索时跳过 ANY(:pids) 条件避免20K元素数组导致全表扫描
    product_ids = await _resolve_products(db, search_product) if search_product else None
    if search_product and not product_ids:
        return _empty_inventory_response(page, per_page)

    params, clauses, pids_param = _build_inventory_filter_params(
        search_product, search_customer, product_ids, stock_status, factory,
    )
    cte_sql = _build_inventory_cte_sql(clauses)

    params['limit'] = per_page
    params['offset'] = (page - 1) * per_page

    # 设置 work_mem 提升大查询性能（避免磁盘溢出）
    await db.execute(text("SET LOCAL work_mem = '64MB'"))
    result = await db.execute(cte_sql, params)
    rows = result.all()

    # 独立查询所有客户列表（不受客户筛选影响，确保客户栏始终显示全部客户）
    all_customers = await _get_all_customers(db, pids_param if search_product else None, factory)

    if not rows:
        return _empty_inventory_response(page, per_page, all_customers=all_customers)

    inventory_data, total_items, sum_stockin, sum_order, sum_stock, total_available_stock = \
        _format_inventory_rows(rows)

    return {
        'inventory_data': inventory_data,
        'total_order_qty': sum_order,
        'total_stockin_qty': sum_stockin,
        'total_stock': sum_stock,
        'total_available_stock': total_available_stock,
        'all_customers': all_customers,
        'total_items': total_items,
        'page': page,
        'per_page': per_page,
    }


async def get_inventory_balance(db: AsyncSession, product_id: int) -> int:
    """单产品「库存（结余）」= 包装部入库 − 已出货。**「能不能出货」的唯一尺子。**

    ── 业务口径（2026-10-24 业务负责人确认，改动前请先读完这段）──────────────
    举一个真实例子，五步走完两个数字的关系：
        ① 客户下单 10000 + 备货 10000  → 订单 10000 / 备货 10000，总需求 20000
        ② 客户再下单 5000 并抵扣备货    → 订单 15000 / 备货 5000，总需求仍是 20000
        ③ 包装部入库 10000             → 结余 10000，此时最多只能出 10000
        ④ 出货 10000                   → 结余 0
        ⑤ 结果                         → 剩订单 5000 / 备货 5000，无货可出
    原话：「填充 / 手工的数据不计入库存，只有包装入库的计入库存。」

    ── 为什么只算包装部入库（其余来源为什么不进结余）──────────────────────
    · 备货入库：给客户预留的原料/半成品，不是可发成品 → 不进结余；
    · 填充部 / 手工部入库：仍是半成品，要经包装才算成品 → 不进结余；
    · 订单抵扣（含取消抵扣/抵扣回滚）：只是把「备货」额度挪成「订单」额度，
      货没动；而且抵扣三型若只计一侧（删单时计「抵扣回滚」、建单时「订单抵扣」
      从未计入），结余会虚高回滚量（Round16 核实）→ 三型整体不进结余。
    所以**不能用 product.current_stock 当出货闸门**：它含上述全部来源，恒 ≥ 结余，
    用它判会让「备货/半成品直接出货」一路绿灯（2026-10 审计 P1-6 就是这个问题）。

    ── 实现（与 get_inventory_paginated 的 CTE 逐字一致）────────────────────
        包装部入库 = Σ daily_production_record.quantity  (department='packaging')
        已出货     = Σ inventory_log.change_quantity     (change_type in
                     出库 / 出库修改 / 出库删除 / 退货 / 退货取消)   # 出库为负，相加即净流出

    ⚠️ 所有写入口的库存闸门都必须调本函数，**不要另写一套口径**。
       已接入四处：新建出货(create_stockout_core)、编辑出货(update_stockout_core)、
       取消退货(cancel_stockreturn_core)、暂存导入出货(_confirm_one_staging_stockout)。
    ⚠️ 本指标是**产品级**的，不含客户维度 —— /stock 页同一产品在不同客户行上
       显示的是同一个值。
    """
    packaging_qty, shipped_net = await get_inventory_balance_detail(db, product_id)
    return packaging_qty + shipped_net


async def get_inventory_balance_detail(db: AsyncSession, product_id: int) -> tuple[int, int]:
    """返回 (包装部入库, 出货净额)。出货净额为负，结余 = 两者相加。

    拆开返回是为了让**闸门的报错能自解释**：
        「可用 53482（包装部入库 120000 − 已出货 66518），本次 54000」
    只给一个总数时，用户无法判断是「没包装够」还是「订单/本次出货量填多了」，
    只能回来问人（2026-10-24 生产实例）。
    """
    packaging_qty = (await db.execute(
        select(func.coalesce(func.sum(DailyProductionRecord.quantity), 0)).where(
            DailyProductionRecord.department == 'packaging',
            DailyProductionRecord.product_id == product_id,
        )
    )).scalar() or 0
    shipped_net = (await db.execute(
        select(func.coalesce(func.sum(InventoryLog.change_quantity), 0)).where(
            InventoryLog.change_type.in_(
                ('出库', '出库修改', '出库删除',
                 '退货', '退货取消')),
            InventoryLog.product_id == product_id,
        )
    )).scalar() or 0
    return int(packaging_qty), int(shipped_net)


def _build_inventory_filter_params(search_product: str, search_customer: str,
                                   product_ids: list[int] | None,
                                   stock_status: str = '',
                                   factory: str = '') -> tuple[dict, dict, tuple[int, ...] | None]:
    """构建库存查询的过滤参数和SQL片段。

    Returns:
        (params, clauses) - params: 查询参数字典; clauses: SQL片段字典
    """
    params: dict = {'sc_is_empty': not bool(search_customer), 'stock_status': stock_status}
    # 工厂隔离（P0-2）：值走绑定参数 :factory，SQL 片段为模块内常量。
    prod_factory = ''
    if factory:
        params['factory'] = factory
        prod_factory = " AND (p.factory = :factory OR p.factory IS NULL OR p.factory = '')"
    pid_clause = ''
    pids_param = None
    if search_product and product_ids:
        pids_param = tuple(product_ids)
        params['pids'] = pids_param
        pid_clause = _SI_PID

    si_cust = so_cust = o_cust = cust_clause = ''
    if search_customer:
        params['sc'] = search_customer
        si_cust = _SI_CUST
        so_cust = _SO_CUST
        o_cust = _O_CUST
        cust_clause = _CUST_CLAUSE

    # 各表的产品过滤条件（无搜索时为空字符串，避免 ANY(:pids) 全表扫描）
    si_pid = _SI_PID if search_product else ''
    so_pid = _SO_PID if search_product else ''
    o_pid = _O_PID if search_product else ''
    oi_or_o_pid = _OI_OR_O_PID if search_product else ''
    sub_pid = _PID_CLAUSE if search_product else ''
    prod_pid = _PROD_PID if search_product else ''
    pso_pid = _PID_CLAUSE if search_product else ''

    clauses = {
        'pid_clause': pid_clause, 'si_cust': si_cust, 'so_cust': so_cust,
        'o_cust': o_cust, 'cust_clause': cust_clause,
        'si_pid': si_pid, 'so_pid': so_pid, 'o_pid': o_pid,
        'oi_or_o_pid': oi_or_o_pid,
        'sub_pid': sub_pid, 'prod_pid': prod_pid, 'pso_pid': pso_pid,
        'o_not_deleted': _O_NOT_DELETED, 'prod_factory': prod_factory,
    }
    return params, clauses, pids_param


def _build_inventory_cte_sql(clauses: dict) -> TextClause:
    """构建库存CTE查询SQL。

    Returns:
        TextClause: 已编译好的 CTE 查询。

    注：原注解为 ``-> tuple``、docstring 写「(cte_sql, country)」，
    与实际返回（单个 TextClause，调用方也按单值接收）不符，已一并修正。
    """
    c = clauses
    # 安全说明：clauses 中所有 SQL 片段均来自模块级常量（_SI_PID/_SO_CUST 等），
    # 不含用户输入；筛选值通过 :pids/:sc 绑定参数传递。重构为完全参数化会
    # 改变 CTE 语义，风险过高，故保留并标注。
    cte_sql = text(f"""
WITH stockin_agg AS (
    SELECT si.product_id, si.customer,
           SUM(si.quantity - COALESCE(sub.consumed, 0)) AS stockin_qty,
           1 AS has_stockin
    FROM stock_in si
    LEFT JOIN (
        SELECT stockin_id, SUM(quantity - returned_quantity) AS consumed
        FROM stock_out WHERE stockin_id IS NOT NULL{c['sub_pid']}
        GROUP BY stockin_id
    ) sub ON sub.stockin_id = si.id
    WHERE 1=1{c['si_pid']}{c['si_cust']}
    GROUP BY si.product_id, si.customer
),
stockout_agg AS (
    SELECT so.product_id, so.customer,
        SUM(CASE WHEN so.order_id IS NULL THEN so.quantity - so.returned_quantity ELSE 0 END) AS direct_stockout_qty,
        SUM(CASE WHEN so.order_id IS NOT NULL THEN so.quantity - so.returned_quantity ELSE 0 END) AS order_stockout_qty
    FROM stock_out so
    WHERE so.stockin_id IS NULL{c['so_pid']}{c['so_cust']}
    GROUP BY so.product_id, so.customer
),
order_agg AS (
    -- 多 SKU：按 OrderItem 维度聚合；无明细订单（批量导入兼容路径）回退订单级字段
    SELECT COALESCE(oi.product_id, o.product_id) AS product_id,
        o.customer,
        SUM(COALESCE(oi.quantity, o.quantity)) AS order_qty,
        1 AS has_order
    FROM "order" o
    LEFT JOIN order_item oi ON oi.order_id = o.id
    WHERE 1=1{c['oi_or_o_pid']}{c['o_cust']}{c['o_not_deleted']}
    GROUP BY COALESCE(oi.product_id, o.product_id), o.customer
),
production_agg AS (
    SELECT product_id,
        SUM(quantity) AS production_qty,
        SUM(CASE WHEN department = 'packaging' THEN quantity ELSE 0 END) AS packaging_qty
    FROM daily_production_record
    WHERE product_id IS NOT NULL{c['prod_pid']}
    GROUP BY product_id
),
packaging_production_products AS (
    SELECT product_id
    FROM production_agg
    WHERE packaging_qty > 0
),
product_stockout_total AS (
    SELECT product_id, SUM(quantity - returned_quantity) AS total_stockout_qty
    FROM stock_out
    WHERE 1=1{c['pso_pid']}
    GROUP BY product_id
),
merged AS (
    SELECT
        COALESCE(si.product_id, so.product_id, od.product_id, pp.product_id) AS product_id,
        COALESCE(si.customer, so.customer, od.customer, '') AS customer,
        COALESCE(si.stockin_qty, 0) AS stockin_qty,
        CASE WHEN si.product_id IS NOT NULL THEN true ELSE false END AS has_stockin,
        COALESCE(so.direct_stockout_qty, 0) AS direct_stockout_qty,
        COALESCE(so.order_stockout_qty, 0) AS order_stockout_qty,
        COALESCE(od.order_qty, 0) AS order_qty,
        CASE WHEN od.product_id IS NOT NULL THEN true ELSE false END AS has_order,
        CASE WHEN pp.product_id IS NOT NULL THEN true ELSE false END AS has_packaging_production
    FROM stockin_agg si
    FULL OUTER JOIN stockout_agg so ON si.product_id = so.product_id AND si.customer = so.customer
    FULL OUTER JOIN order_agg od
        ON COALESCE(si.product_id, so.product_id) = od.product_id
        AND COALESCE(si.customer, so.customer) = od.customer
    FULL OUTER JOIN packaging_production_products pp
        ON COALESCE(si.product_id, so.product_id, od.product_id) = pp.product_id
),
inventory_calc AS (
    SELECT m.*,
        GREATEST(0, m.order_qty - m.direct_stockout_qty - m.order_stockout_qty) AS remaining,
        m.stockin_qty + GREATEST(0, m.order_qty - m.direct_stockout_qty - m.order_stockout_qty) AS total_qty
    FROM merged m
),
filtered AS (
    SELECT ic.*, p.name AS product_name, p.barcode AS product_barcode,
        COALESCE(pa.production_qty, 0) AS production_qty,
        COALESCE(pst.total_stockout_qty, 0) AS total_product_stockout,
        COALESCE(pa.production_qty, 0) - COALESCE(pst.total_stockout_qty, 0) AS available_stock,
        -- 库存（结余）= 包装部入库 − 已出货（2026-10-07 业务裁定，口径见快照）
        COALESCE(pa.packaging_qty, 0) + COALESCE(ship.shipped_net, 0) AS inventory_balance
    FROM inventory_calc ic
    JOIN product p ON p.id = ic.product_id{c.get('prod_factory', '')}
    LEFT JOIN production_agg pa ON pa.product_id = ic.product_id
    LEFT JOIN product_stockout_total pst ON pst.product_id = ic.product_id
    LEFT JOIN (
        -- 出货台账（inventory_log，出库为负数，故求和即净流出）：出货三型 + 退货。
        -- 抵扣三型（订单抵扣/取消抵扣/抵扣回滚）不进结余：抵扣期间两侧对称净影响为零，
        --   删单时的「抵扣回滚」若计入而「订单抵扣」从未计入，结余虚高回滚量（Round16 核实）。
        -- 退货/退货取消：退货回补 +qty、取消再冲回 −qty；漏掉则结余不随退货变动
        --   （2026-10-08 实测：退货 2500 后结余纹丝不动）。
        SELECT product_id, SUM(change_quantity) AS shipped_net
        FROM inventory_log
        WHERE change_type IN ('出库', '出库修改', '出库删除',
                              '退货', '退货取消')
              AND product_id IS NOT NULL
        GROUP BY product_id
    ) ship ON ship.product_id = ic.product_id
    WHERE (ic.has_stockin OR ic.has_order OR (ic.has_packaging_production AND :sc_is_empty))
      AND (ic.total_qty > 0 OR (ic.has_packaging_production AND :sc_is_empty))
)
SELECT f.product_id, f.customer, f.product_name, f.product_barcode,
    f.stockin_qty, f.direct_stockout_qty, f.order_stockout_qty,
    f.order_qty, f.remaining, f.total_qty,
    f.production_qty, f.available_stock, f.inventory_balance,
    COUNT(*) OVER() AS total_count,
    SUM(f.stockin_qty) OVER() AS sum_stockin,
    SUM(f.remaining) OVER() AS sum_order,
    SUM(f.total_qty) OVER() AS sum_stock
FROM filtered f
WHERE (:stock_status <> 'zero' OR f.inventory_balance <= 0)
  AND (:stock_status <> 'active' OR f.inventory_balance > 0)
ORDER BY f.customer, f.product_name
LIMIT :limit OFFSET :offset
""")  # nosec B608 - clauses 为模块级常量，值通过绑定参数传递
    return cte_sql


def _format_inventory_rows(rows) -> tuple[list, int, int, int, int, int]:
    """格式化库存查询结果行。

    Returns:
        (inventory_data, total_items, sum_stockin, sum_order, sum_stock, total_available_stock)
    """
    first = rows[0]
    total_items = first.total_count
    sum_stockin = int(first.sum_stockin)
    sum_order = int(first.sum_order)
    sum_stock = int(first.sum_stock)

    inventory_data = []
    seen_products: set[int] = set()
    total_available_stock = 0
    for row in rows:
        so_total = int(row.direct_stockout_qty) + int(row.order_stockout_qty)
        remaining = int(row.remaining)

        production_qty = int(row.production_qty)
        available_stock = int(row.available_stock)

        if row.product_id not in seen_products:
            seen_products.add(row.product_id)
            total_available_stock += available_stock

        inventory_data.append({
            # 2026-10-18 OCR 评审：移动端需要稳定行键/产品 ID；此前响应无 product_id
            'product_id': row.product_id,
            'customer': row.customer,
            'product_name': row.product_name,
            'product_barcode': row.product_barcode or '',
            'order_quantity': remaining if remaining > 0 else '',
            'stockin_quantity': int(row.stockin_qty) if int(row.stockin_qty) > 0 else '',
            'stockout_quantity': so_total if so_total > 0 else '',
            'total_stock': int(row.total_qty) if int(row.total_qty) > 0 else '',
            'production_qty': production_qty if production_qty > 0 else '',
            'available_stock': available_stock if available_stock != 0 else '',
            # 库存（结余）：0 与负数都要显示（不是「空值」），故原样输出
            'inventory_balance': int(row.inventory_balance),
        })

    return inventory_data, total_items, sum_stockin, sum_order, sum_stock, total_available_stock


def _empty_inventory_response(page: int = 1, per_page: int = 50, all_customers: list | None = None) -> dict:
    """构造空库存响应"""
    return {
        'inventory_data': [],
        'total_order_qty': 0,
        'total_stockin_qty': 0,
        'total_stock': 0,
        'total_available_stock': 0,
        'all_customers': all_customers or [],
        'total_items': 0,
        'page': page,
        'per_page': per_page,
    }


@cache_result(key_prefix="customers:all", ttl=120, local_ttl=60,
              key_builder=lambda **kwargs: f"pids{hashlib.sha256(str(kwargs.get('pids', '')).encode()).hexdigest()[:16] if kwargs.get('pids') else 'all'}-f:{kwargs.get('factory', '') or ''}")
async def _get_all_customers(db: AsyncSession, pids: tuple | None, factory: str = '') -> list[str]:
    """获取客户快捷切换栏客户列表：成员 = 库存表格里可能出现的客户，按最近活动排序。

    成员规则（2026-09-30 修正）：必须与库存表格行的来源口径一致。表格行来自
    stock_in ⟗ stock_out ⟗ order 三表合并，凡「只有备货、没有有效订单」的客户
    （线上实例：MINISO国际，只有备货 10000 件、10 条订单已全部软删除）同样成行；
    切换栏若只看 order 表就会漏掉它们，表现为「表格里看得见、chips 里筛不了」。
    因此成员 = 出现在 stock_in 或「未软删 order」里的客户。

    stock_out 不入成员：出库行不产生 has_stockin/has_order，只有当同一 客户+产品
    另有备货或订单时才随其成行；「只有出库」的客户既不显示也无法被筛，
    并入只会多出点了就空的 chip。

    排序口径：
    1) last_activity：MAX(order_date / stockin_date)，最近有下单或备货的客户置顶；
    2) activity_cnt：两表命中行数之和，时间相同则记录多的靠前；
    3) customer：名称升序，保证结果稳定。

    背景：切换栏是单行横向滚动条（nowrap + 隐藏滚动条），排在末尾的客户会被裁出首屏，
    需滚动才可见；旧版按 Unicode 码点排序无法把常用客户置顶。
    """
    # pid_clause 为常量 SQL 片段（ANY(:pids)），备货/订单两个来源共用，
    # 不拼接用户输入，安全
    pid_clause = ' AND product_id = ANY(:pids)' if pids else ''
    # 工厂隔离（P0-2）：客户快捷栏同样只列本厂产品涉及的客户。
    factory_clause = " AND product_id IN (SELECT id FROM product WHERE factory = :factory OR factory IS NULL OR factory = '')" if factory else ''
    sql = text(f"""
        WITH activity AS (
            SELECT customer, MAX(order_date) AS last_activity, COUNT(*) AS activity_cnt
            FROM "order"
            WHERE customer IS NOT NULL AND is_deleted IS NOT TRUE AND quantity > 0{pid_clause}{factory_clause}
            GROUP BY customer
            UNION ALL
            SELECT customer, MAX(stockin_date) AS last_activity, COUNT(*) AS activity_cnt
            FROM stock_in
            WHERE customer IS NOT NULL{pid_clause}{factory_clause}
            GROUP BY customer
        )
        SELECT customer, MAX(last_activity) AS last_activity,
               SUM(activity_cnt) AS activity_cnt
        FROM activity
        GROUP BY customer
        ORDER BY last_activity DESC NULLS LAST, activity_cnt DESC, customer ASC
    """)
    bind_params: dict = {}
    if pids:
        bind_params['pids'] = pids
    if factory:
        bind_params['factory'] = factory
    result = await db.execute(sql, bind_params) if bind_params else await db.execute(sql)
    return [row[0] for row in result.all()]


async def _resolve_products(db: AsyncSession, search: str) -> list[int] | None:
    """解析产品ID列表。无搜索时返回 None（表示不限制产品），避免全量加载。"""
    if not search:
        return None  # 无搜索时不加载全量产品ID，调用方应跳过 ANY(:pids) 条件
    escaped = escape_like(search)
    # OCR 复审（2026-10-17 low）：改用 ilike——移动端/桌面端本地过滤原先都是
    # toLowerCase() 双侧大小写不敏感，like 在 PG 是大小写敏感的，混合大小写
    # 查询（如 m01 搜 M01）会假阴性。与 /products/list 的 ilike 口径一致。
    result = await db.execute(select(Product.id).where(or_(Product.name.ilike(f'%{escaped}%', escape='\\'), Product.barcode.ilike(f'%{escaped}%', escape='\\'))))  # sql-safe: escape_like/绑定参数/常量片段
    return [row[0] for row in result.all()]


async def get_stock_overview_stats(db: AsyncSession, factory: str = '') -> dict:
    """库存统计聚合（自 stock.py 端点下沉）：订单数量与备货数量。

    多 SKU：按 OrderItem 维度统计；无明细订单（批量导入兼容路径）回退
    订单级字段（COALESCE），单 SKU 订单行为与旧实现一致。
    """
    item_qty = func.coalesce(OrderItem.quantity, Order.quantity)
    base = (
        select(func.coalesce(func.sum(item_qty), 0))
        .select_from(Order)
        .outerjoin(OrderItem, OrderItem.order_id == Order.id)
        .where(Order.is_deleted.isnot(True))
    )
    order_quantity_stmt = base
    stockin_quantity_stmt = select(func.coalesce(func.sum(StockIn.quantity), 0))
    if factory:
        # 工厂隔离（P0-2）：订单按明细产品（兼容路径回退订单级产品）归属工厂。
        order_quantity_stmt = order_quantity_stmt.where(
            func.coalesce(OrderItem.product_id, Order.product_id).in_(
                select(Product.id).where(_factory_match(factory))
            )
        )
        stockin_quantity_stmt = stockin_quantity_stmt.join(
            Product, Product.id == StockIn.product_id
        ).where(_factory_match(factory))
    order_quantity = int((await db.execute(order_quantity_stmt)).scalar() or 0)

    stockin_quantity = int((await db.execute(stockin_quantity_stmt)).scalar() or 0)

    return {
        'order_quantity': order_quantity,
        'stockin_quantity': stockin_quantity,
    }

