"""
库存查询业务逻辑（列表 / 库存聚合 / 统计）

包含入库/出库/退货列表查询（get_stockins/get_stockouts/get_stockreturns）、
库存聚合查询（get_inventory/get_inventory_paginated）及其 SQL 聚合辅助函数、
库存统计（get_stock_overview_stats）。

模块级 SQL 片段常量（_SI_PID/_SO_CUST 等）仅在此处使用，随函数一并迁移至此。
"""
import hashlib
from datetime import UTC, datetime

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from fastapi_app.core.cache import cache_result
from fastapi_app.core.sanitizer import escape_like
from fastapi_app.shared_models import Order, OrderItem, Product, StockIn, StockOut, StockReturn

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


@cache_result(
    key_prefix='stockins:list',
    ttl=30,
    local_ttl=10,
    key_builder=lambda *args, **kwargs: f"pg:{kwargs.get('page',1)}:pp:{kwargs.get('per_page',50)}:c:{kwargs.get('customer','') or ''}:ot:{kwargs.get('order_type','') or ''}:sd:{kwargs.get('start_date','') or ''}:ed:{kwargs.get('end_date','') or ''}",
)
async def get_stockins(db: AsyncSession, page: int=1, per_page: int=50,
                       customer: str | None = None, order_type: str | None = None,
                       start_date: str | None = None, end_date: str | None = None) -> dict:
    """获取入库列表（含关联数据，支持分页和筛选）- SQL子查询优化版"""
    conditions = []
    if customer:
        conditions.append(StockIn.customer.like(f'%{escape_like(customer)}%'))
    if order_type:
        conditions.append(StockIn.order_type == order_type)
    if start_date:
        try:
            from datetime import datetime
            sd = datetime.strptime(start_date, '%Y-%m-%d').replace(tzinfo=UTC)
            conditions.append(StockIn.stockin_date >= sd)
        except ValueError:
            pass  # defensive: 可选 ValueError 静默处理,不影响主流程
    if end_date:
        try:
            from datetime import datetime
            ed = datetime.strptime(end_date, '%Y-%m-%d').replace(hour=23, minute=59, second=59, tzinfo=UTC)
            conditions.append(StockIn.stockin_date <= ed)
        except ValueError:
            pass  # defensive: 可选 ValueError 静默处理,不影响主流程

    base_where = select(StockIn.id)
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
            'stockin_date': stock_in.stockin_date.strftime('%Y-%m-%d') if stock_in.stockin_date else '',
            'customer': stock_in.customer,
            'product': {'id': stock_in.product.id, 'name': stock_in.product.name, 'barcode': stock_in.product.barcode or '', 'image': stock_in.product.image or ''} if stock_in.product else None,
            'quantity': stock_in.quantity,
            'order_type': stock_in.order_type or 'regular',
            'country': stock_in.country or '',
            'deducted': deducted,
            'note': stock_in.note or '',
        })
    return {'items': data, 'total': total, 'page': page, 'per_page': per_page}


@cache_result(
    key_prefix='stockouts:list',
    ttl=30,
    local_ttl=10,
    key_builder=lambda *args, **kwargs: f"pg:{kwargs.get('page',1)}:pp:{kwargs.get('per_page',50)}:c:{kwargs.get('customer','') or ''}:ot:{kwargs.get('order_type','') or ''}:sd:{kwargs.get('start_date','') or ''}:ed:{kwargs.get('end_date','') or ''}",
)
async def get_stockouts(db: AsyncSession, page: int=1, per_page: int=50,
                        customer: str | None = None, order_type: str | None = None,
                        start_date: str | None = None, end_date: str | None = None) -> dict:
    """获取出库列表（仅独立出库，非抵扣，支持分页和筛选）

    筛选维度：customer（模糊匹配）、order_type（需 JOIN Order，regular 含无订单记录）、
    start_date/end_date（按 stockout_date 过滤）。
    """
    from fastapi_app.shared_models import Order, OrderItem

    conditions = [StockOut.stockin_id.is_(None)]
    needs_order_join = False
    if customer:
        conditions.append(StockOut.customer.like(f'%{escape_like(customer)}%'))
    if order_type:
        needs_order_join = True
        # 多 SKU：出库类型按匹配明细（order_id+product_id）判定，无匹配明细回退订单级兼容字段；
        # regular 包含无关联订单的出库（前端展示时默认为 regular）
        item_type = func.coalesce(OrderItem.order_type, Order.order_type)
        if order_type == 'regular':
            conditions.append(or_(StockOut.order_id.is_(None), item_type == 'regular'))
        else:
            conditions.append(item_type == order_type)
    if start_date:
        try:
            sd = datetime.strptime(start_date, '%Y-%m-%d').replace(tzinfo=UTC)
            conditions.append(StockOut.stockout_date >= sd)
        except ValueError:
            pass  # defensive: 可选 ValueError 静默处理,不影响主流程
    if end_date:
        try:
            ed = datetime.strptime(end_date, '%Y-%m-%d').replace(hour=23, minute=59, second=59, tzinfo=UTC)
            conditions.append(StockOut.stockout_date <= ed)
        except ValueError:
            pass  # defensive: 可选 ValueError 静默处理,不影响主流程

    # 先用子查询过滤 + 分页取 ID，再按 ID 批量加载关联数据，避免 joinedload 与过滤 JOIN 冲突
    id_query = select(StockOut.id)
    if needs_order_join:
        if order_type == 'regular':
            id_query = id_query.outerjoin(Order, StockOut.order_id == Order.id)
        else:
            id_query = id_query.join(Order, StockOut.order_id == Order.id)
        id_query = id_query.outerjoin(
            OrderItem,
            (OrderItem.order_id == StockOut.order_id) & (OrderItem.product_id == StockOut.product_id),
        )
    id_query = id_query.where(*conditions)

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
        # 多 SKU：类型/国家取与出库产品匹配的订单明细，无匹配明细回退订单级兼容字段
        matched = None
        if stock_out.order is not None:
            matched = next(
                (oi for oi in stock_out.order.items if oi.product_id == stock_out.product_id),
                None,
            )
        item_type_val = (
            (matched.order_type if matched else None)
            or (stock_out.order.order_type if stock_out.order else None)
            or 'regular'
        )
        country_val = (
            (matched.country if matched else None)
            or (stock_out.order.country if stock_out.order else None)
            or ''
        )
        item = {
            'id': stock_out.id,
            'stockout_no': stock_out.stockout_no,
            'stockout_date': stock_out.stockout_date.strftime('%Y-%m-%d') if stock_out.stockout_date else '',
            'customer': stock_out.customer,
            'product_id': stock_out.product_id,
            'product_name': stock_out.product.name if stock_out.product else '',
            'product_image': stock_out.product.image if stock_out.product else '',
            'barcode': stock_out.product.barcode if stock_out.product else '',
            'product': {'id': stock_out.product.id, 'name': stock_out.product.name, 'barcode': stock_out.product.barcode or '', 'image': stock_out.product.image or ''} if stock_out.product else None,
            'quantity': stock_out.quantity,
            'returned_quantity': stock_out.returned_quantity,
            'note': stock_out.note or '',
            'order_type': item_type_val,
            'country': country_val,
        }
        data.append(item)
    return {'items': data, 'total': total, 'page': page, 'per_page': per_page}


async def get_stockreturns(db: AsyncSession, stockout_id: int | None = None,
                           page: int = 1, per_page: int = 50) -> dict:
    """获取退货列表（支持按出货ID筛选，支持分页）"""
    # 构建共享过滤条件：stockout_id 为空时不加条件
    # （此前 `== stockout_id if stockout_id else True` 在无筛选时退化为 `== True` 恒假，导致 total 恒为 0）
    conditions = []
    if stockout_id:
        conditions.append(StockReturn.stockout_id == stockout_id)
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
            'return_date': stock_return.return_date.strftime('%Y-%m-%d') if stock_return.return_date else '',
            'product': {'id': stock_return.product.id, 'name': stock_return.product.name} if stock_return.product else None,
            'quantity': stock_return.quantity,
            'customer': stock_return.customer,
            'stockout_id': stock_return.stockout_id,
            'stockout_no': stock_return.stockout.stockout_no if stock_return.stockout else '',
            'reason': stock_return.reason or '',
            'note': stock_return.note or '',
        })
    return {'items': data, 'total': total, 'page': page, 'per_page': per_page}


@cache_result(key_prefix='inventory', ttl=60, local_ttl=30, key_builder=lambda *args, **kwargs: f"c{kwargs.get('search_customer', '')}:p{kwargs.get('search_product', '')}")
async def get_inventory(db: AsyncSession, search_customer: str='', search_product: str='') -> dict:
    """
    获取库存数据（按产品+客户维度汇总）- SQL聚合优化版
    目标：O(P*C*S) 内存聚合 → SQL GROUP BY，响应时间降低 50-80%
    """
    product_ids = await _resolve_products(db, search_product)
    if product_ids is not None and not product_ids:
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
        so_reg = int(row.get('regular_stockout_qty') or 0)
        so_cus = int(row.get('custom_stockout_qty') or 0)
        o_reg = int(row.get('regular_order_qty') or 0)
        o_cus = int(row.get('custom_order_qty') or 0)
        has_si = bool(row.get('has_stockin'))
        has_o = bool(row.get('has_order'))
        so_total = so_dir + so_reg + so_cus
        remaining_reg = max(0, o_reg - so_dir - so_reg)
        remaining_cus = max(0, o_cus - so_cus)
        total_qty = si_qty + remaining_reg + remaining_cus
        has_positive = total_qty > 0
        country_data = {}
        raw = row.get('country_data') or ''
        if raw:
            for item in raw.split('|'):
                if ':' in item:
                    country, qty_str = item.split(':', 1)
                    qty = int(qty_str)
                    country_data[country] = qty
                    if country != '常规':
                        all_countries.add(country)
        if (has_si or has_o) and has_positive:
            inventory_data.append({'customer': customer, 'product_name': pname, 'product_barcode': pbarcode, 'order_quantity': remaining_reg if remaining_reg > 0 else '', 'country_orders': country_data, 'stockin_quantity': si_qty if si_qty > 0 else '', 'stockout_quantity': so_total if so_total > 0 else '', 'total_stock': total_qty if total_qty > 0 else ''})
            total_stockin_qty += si_qty
            total_order_qty += remaining_reg + remaining_cus
            total_stock += total_qty
    return {'inventory_data': inventory_data, 'total_order_qty': total_order_qty, 'total_stockin_qty': total_stockin_qty, 'total_stock': total_stock, 'all_countries': sorted(all_countries)}


@cache_result(key_prefix="inventory:paginated", ttl=120, local_ttl=60,
             key_builder=lambda **kwargs: f"{kwargs.get('search_customer','')}-{kwargs.get('search_product','')}-{kwargs.get('country','')}-{kwargs.get('page',1)}-{kwargs.get('per_page',50)}")
async def get_inventory_paginated(db: AsyncSession, search_customer: str = '', search_product: str = '',
                                  country: str = '', page: int = 1, per_page: int = 50) -> dict:
    """
    库存分页查询 - SQL CTE 优化版
    将4次聚合查询合并为单次 CTE 查询，在数据库层面完成合并、过滤和分页，
    避免加载全量数据到 Python 内存。20K+ 条数据时响应时间从秒级降至百毫秒级。
    """
    # 仅在有产品搜索时才加载产品ID列表；无搜索时跳过 ANY(:pids) 条件避免20K元素数组导致全表扫描
    product_ids = await _resolve_products(db, search_product) if search_product else None
    if search_product and not product_ids:
        return _empty_inventory_response(page, per_page)

    params, clauses, pids_param = _build_inventory_filter_params(search_product, search_customer, product_ids)
    cte_sql = _build_inventory_cte_sql(clauses, country)

    params['limit'] = per_page
    params['offset'] = (page - 1) * per_page
    if country:
        params['country'] = country

    # 设置 work_mem 提升大查询性能（避免磁盘溢出）
    await db.execute(text("SET LOCAL work_mem = '64MB'"))
    result = await db.execute(cte_sql, params)
    rows = result.all()

    # 独立查询所有客户列表（不受客户筛选影响，确保客户栏始终显示全部客户）
    all_customers = await _get_all_customers(db, pids_param if search_product else None)

    if not rows:
        return _empty_inventory_response(page, per_page, all_customers=all_customers)

    inventory_data, total_items, sum_stockin, sum_order, sum_stock, all_countries, total_available_stock = \
        _format_inventory_rows(rows)

    return {
        'inventory_data': inventory_data,
        'total_order_qty': sum_order,
        'total_stockin_qty': sum_stockin,
        'total_stock': sum_stock,
        'total_available_stock': total_available_stock,
        'all_countries': all_countries,
        'all_customers': all_customers,
        'total_items': total_items,
        'page': page,
        'per_page': per_page,
    }


def _build_inventory_filter_params(search_product: str, search_customer: str,
                                   product_ids: list[int] | None) -> tuple[dict, dict]:
    """构建库存查询的过滤参数和SQL片段。

    Returns:
        (params, clauses) - params: 查询参数字典; clauses: SQL片段字典
    """
    params: dict = {}
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
    }
    return params, clauses, pids_param


def _build_inventory_cte_sql(clauses: dict, country: str) -> tuple:
    """构建库存CTE查询SQL。

    Returns:
        (cte_sql, country) - cte_sql: TextClause; country参数由调用方添加
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
        SUM(CASE WHEN so.order_id IS NOT NULL AND (COALESCE(oi.order_type, o.order_type) IS NULL OR COALESCE(oi.order_type, o.order_type) = 'regular')
            THEN so.quantity - so.returned_quantity ELSE 0 END) AS regular_stockout_qty,
        SUM(CASE WHEN COALESCE(oi.order_type, o.order_type) = 'custom' THEN so.quantity - so.returned_quantity ELSE 0 END) AS custom_stockout_qty
    FROM stock_out so
    LEFT JOIN "order" o ON so.order_id = o.id
    LEFT JOIN order_item oi ON oi.order_id = so.order_id AND oi.product_id = so.product_id
    WHERE so.stockin_id IS NULL{c['so_pid']}{c['so_cust']}
    GROUP BY so.product_id, so.customer
),
order_agg AS (
    -- 多 SKU：按 OrderItem 维度聚合；无明细订单（批量导入兼容路径）回退订单级字段
    SELECT COALESCE(oi.product_id, o.product_id) AS product_id,
        o.customer,
        SUM(CASE WHEN COALESCE(oi.order_type, o.order_type) IS NULL OR COALESCE(oi.order_type, o.order_type) = 'regular'
            THEN COALESCE(oi.quantity, o.quantity) ELSE 0 END) AS regular_order_qty,
        SUM(CASE WHEN COALESCE(oi.order_type, o.order_type) = 'custom'
            THEN COALESCE(oi.quantity, o.quantity) ELSE 0 END) AS custom_order_qty,
        1 AS has_order
    FROM "order" o
    LEFT JOIN order_item oi ON oi.order_id = o.id
    WHERE 1=1{c['oi_or_o_pid']}{c['o_cust']}
    GROUP BY COALESCE(oi.product_id, o.product_id), o.customer
),
country_agg AS (
    -- 多 SKU：国家归属明细优先，无明细回退订单级兼容字段
    SELECT COALESCE(oi.product_id, o.product_id) AS product_id,
        o.customer,
        COALESCE(oi.country, o.country, '常规') AS country, SUM(COALESCE(oi.quantity, o.quantity)) AS qty
    FROM "order" o
    LEFT JOIN order_item oi ON oi.order_id = o.id
    WHERE COALESCE(oi.order_type, o.order_type) = 'custom'{c['oi_or_o_pid']}{c['o_cust']}
    GROUP BY COALESCE(oi.product_id, o.product_id), o.customer, COALESCE(oi.country, o.country, '常规')
),
country_stockout_agg AS (
    SELECT so.product_id, o.customer,
        COALESCE(oi.country, o.country, '常规') AS country,
        SUM(so.quantity - so.returned_quantity) AS shipped_qty
    FROM stock_out so
    JOIN "order" o ON so.order_id = o.id
    LEFT JOIN order_item oi ON oi.order_id = so.order_id AND oi.product_id = so.product_id
    WHERE so.stockin_id IS NULL AND COALESCE(oi.order_type, o.order_type) = 'custom'{c['so_pid']}{c['so_cust']}
    GROUP BY so.product_id, o.customer, COALESCE(oi.country, o.country, '常规')
),
production_agg AS (
    SELECT product_id, SUM(quantity) AS production_qty
    FROM daily_production_record
    WHERE product_id IS NOT NULL{c['prod_pid']}
    GROUP BY product_id
),
product_stockout_total AS (
    SELECT product_id, SUM(quantity - returned_quantity) AS total_stockout_qty
    FROM stock_out
    WHERE 1=1{c['pso_pid']}
    GROUP BY product_id
),
merged AS (
    SELECT
        COALESCE(si.product_id, so.product_id, od.product_id) AS product_id,
        COALESCE(si.customer, so.customer, od.customer) AS customer,
        COALESCE(si.stockin_qty, 0) AS stockin_qty,
        CASE WHEN si.product_id IS NOT NULL THEN true ELSE false END AS has_stockin,
        COALESCE(so.direct_stockout_qty, 0) AS direct_stockout_qty,
        COALESCE(so.regular_stockout_qty, 0) AS regular_stockout_qty,
        COALESCE(so.custom_stockout_qty, 0) AS custom_stockout_qty,
        COALESCE(od.regular_order_qty, 0) AS regular_order_qty,
        COALESCE(od.custom_order_qty, 0) AS custom_order_qty,
        CASE WHEN od.product_id IS NOT NULL THEN true ELSE false END AS has_order
    FROM stockin_agg si
    FULL OUTER JOIN stockout_agg so ON si.product_id = so.product_id AND si.customer = so.customer
    FULL OUTER JOIN order_agg od
        ON COALESCE(si.product_id, so.product_id) = od.product_id
        AND COALESCE(si.customer, so.customer) = od.customer
),
inventory_calc AS (
    SELECT m.*,
        GREATEST(0, m.regular_order_qty - m.direct_stockout_qty - m.regular_stockout_qty) AS remaining_reg,
        GREATEST(0, m.custom_order_qty - m.custom_stockout_qty) AS remaining_cus,
        m.stockin_qty + GREATEST(0, m.regular_order_qty - m.direct_stockout_qty - m.regular_stockout_qty)
            + GREATEST(0, m.custom_order_qty - m.custom_stockout_qty) AS total_qty
    FROM merged m
),
filtered AS (
    SELECT ic.*, p.name AS product_name, p.barcode AS product_barcode,
        COALESCE(pa.production_qty, 0) AS production_qty,
        COALESCE(pst.total_stockout_qty, 0) AS total_product_stockout,
        COALESCE(pa.production_qty, 0) - COALESCE(pst.total_stockout_qty, 0) AS available_stock
    FROM inventory_calc ic
    JOIN product p ON p.id = ic.product_id
    LEFT JOIN production_agg pa ON pa.product_id = ic.product_id
    LEFT JOIN product_stockout_total pst ON pst.product_id = ic.product_id
    WHERE (ic.has_stockin OR ic.has_order) AND ic.total_qty > 0
    {"AND EXISTS (SELECT 1 FROM country_agg ca WHERE ca.product_id = ic.product_id AND ca.customer = ic.customer AND ca.country = :country)" if country else ""}
),
all_countries_cte AS (
    SELECT STRING_AGG(DISTINCT ca.country, '|') AS countries
    FROM country_agg ca WHERE ca.country != '常规'
)
SELECT f.product_id, f.customer, f.product_name, f.product_barcode,
    f.stockin_qty, f.direct_stockout_qty, f.regular_stockout_qty, f.custom_stockout_qty,
    f.regular_order_qty, f.custom_order_qty, f.remaining_reg, f.remaining_cus, f.total_qty,
    f.production_qty, f.available_stock,
    (SELECT STRING_AGG((ca.country || ':' || GREATEST(0, ca.qty - COALESCE(csa.shipped_qty, 0)))::text, '|')
     FROM country_agg ca
     LEFT JOIN country_stockout_agg csa
       ON csa.product_id = ca.product_id AND csa.customer = ca.customer AND csa.country = ca.country
     WHERE ca.product_id = f.product_id AND ca.customer = f.customer) AS country_data,
    (SELECT countries FROM all_countries_cte) AS all_countries_str,
    COUNT(*) OVER() AS total_count,
    SUM(f.stockin_qty) OVER() AS sum_stockin,
    SUM(f.remaining_reg + f.remaining_cus) OVER() AS sum_order,
    SUM(f.total_qty) OVER() AS sum_stock
FROM filtered f
ORDER BY f.customer, f.product_name
LIMIT :limit OFFSET :offset
""")  # nosec B608 - clauses 为模块级常量，值通过绑定参数传递
    return cte_sql


def _format_inventory_rows(rows) -> tuple[list, int, int, int, int, list[str]]:
    """格式化库存查询结果行。

    Returns:
        (inventory_data, total_items, sum_stockin, sum_order, sum_stock, all_countries)
    """
    first = rows[0]
    total_items = first.total_count
    sum_stockin = int(first.sum_stockin)
    sum_order = int(first.sum_order)
    sum_stock = int(first.sum_stock)
    all_countries = sorted(first.all_countries_str.split('|')) if first.all_countries_str else []

    inventory_data = []
    seen_products: set[int] = set()
    total_available_stock = 0
    for row in rows:
        country_data = _parse_country_data(row.country_data or '')
        so_total = int(row.direct_stockout_qty) + int(row.regular_stockout_qty) + int(row.custom_stockout_qty)
        remaining_reg = int(row.remaining_reg)
        int(row.remaining_cus)
        production_qty = int(row.production_qty)
        available_stock = int(row.available_stock)

        if row.product_id not in seen_products:
            seen_products.add(row.product_id)
            total_available_stock += available_stock

        inventory_data.append({
            'customer': row.customer,
            'product_name': row.product_name,
            'product_barcode': row.product_barcode or '',
            'order_quantity': remaining_reg if remaining_reg > 0 else '',
            'country_orders': country_data,
            'stockin_quantity': int(row.stockin_qty) if int(row.stockin_qty) > 0 else '',
            'stockout_quantity': so_total if so_total > 0 else '',
            'total_stock': int(row.total_qty) if int(row.total_qty) > 0 else '',
            'production_qty': production_qty if production_qty > 0 else '',
            'available_stock': available_stock if available_stock != 0 else '',
        })

    return inventory_data, total_items, sum_stockin, sum_order, sum_stock, all_countries, total_available_stock


def _empty_inventory_response(page: int = 1, per_page: int = 50, all_countries: list | None = None, all_customers: list | None = None) -> dict:
    """构造空库存响应"""
    return {
        'inventory_data': [],
        'total_order_qty': 0,
        'total_stockin_qty': 0,
        'total_stock': 0,
        'total_available_stock': 0,
        'all_countries': all_countries or [],
        'all_customers': all_customers or [],
        'total_items': 0,
        'page': page,
        'per_page': per_page,
    }


def _parse_country_data(raw: str) -> dict:
    """解析 country_data 字符串为字典"""
    country_data: dict[str, int] = {}
    if not raw:
        return country_data
    for item in raw.split('|'):
        if ':' in item:
            country, qty = item.split(':', 1)
            country_data[country] = int(qty)
    return country_data


async def _get_all_countries(db: AsyncSession, pids: tuple | None, search_customer: str = '') -> list[str]:
    """获取所有定制国家列表"""
    cust_clause = _CUST_CLAUSE if search_customer else ''
    pid_clause = _OI_OR_O_PID if pids else ''
    params: dict = {}
    if pids:
        params['pids'] = pids
    if search_customer:
        params['sc'] = search_customer
    # 安全说明：pid_clause/cust_clause 均为模块级常量（_OI_OR_O_PID/_CUST_CLAUSE），
    # 不含用户输入；筛选值通过 :pids/:sc 绑定参数传递。
    # 多 SKU：国家取订单明细维度，无明细订单回退订单级兼容字段
    sql = text(f"""
        SELECT DISTINCT COALESCE(oi.country, o.country, '常规') AS country
        FROM "order" o
        LEFT JOIN order_item oi ON oi.order_id = o.id
        WHERE COALESCE(oi.order_type, o.order_type) = 'custom'{pid_clause}{cust_clause}
          AND COALESCE(oi.country, o.country) IS NOT NULL AND COALESCE(oi.country, o.country) != '常规'
    """)  # nosec B608 - pid_clause/cust_clause 为模块级常量，值通过绑定参数传递
    result = await db.execute(sql, params)
    return sorted(row[0] for row in result.all())


@cache_result(key_prefix="customers:all", ttl=120, local_ttl=60,
              key_builder=lambda **kwargs: f"pids{hashlib.sha256(str(kwargs.get('pids', '')).encode()).hexdigest()[:16] if kwargs.get('pids') else 'all'}")
async def _get_all_customers(db: AsyncSession, pids: tuple | None) -> list[str]:
    """获取所有客户列表（120s 缓存，客户列表变更频率低）"""
    if pids:
        sql = text("""
            SELECT DISTINCT customer FROM (
                SELECT DISTINCT customer FROM stock_in WHERE product_id = ANY(:pids) AND customer IS NOT NULL
                UNION
                SELECT DISTINCT customer FROM stock_out WHERE product_id = ANY(:pids) AND customer IS NOT NULL
                UNION
                SELECT DISTINCT customer FROM "order" WHERE product_id = ANY(:pids) AND customer IS NOT NULL
            ) sub
        """)
        result = await db.execute(sql, {'pids': pids})
    else:
        sql = text("""
            SELECT DISTINCT customer FROM (
                SELECT DISTINCT customer FROM stock_in WHERE customer IS NOT NULL
                UNION
                SELECT DISTINCT customer FROM stock_out WHERE customer IS NOT NULL
                UNION
                SELECT DISTINCT customer FROM "order" WHERE customer IS NOT NULL
            ) sub
        """)
        result = await db.execute(sql)
    return sorted(row[0] for row in result.all())


async def _resolve_products(db: AsyncSession, search: str) -> list[int] | None:
    """解析产品ID列表。无搜索时返回 None（表示不限制产品），避免全量加载。"""
    if not search:
        return None  # 无搜索时不加载全量产品ID，调用方应跳过 ANY(:pids) 条件
    escaped = escape_like(search)
    result = await db.execute(select(Product.id).where(or_(Product.name.like(f'%{escaped}%', escape='\\'), Product.barcode.like(f'%{escaped}%', escape='\\'))))  # sql-safe: escape_like/绑定参数/常量片段
    return [row[0] for row in result.all()]


def _build_inventory_query_clauses(pids: list[int] | None, cust: str) -> tuple[dict, str, str, str, str, str, str, str]:
    """构建库存查询的参数和条件片段（无产品筛选时跳过 ANY(:pids) 避免全表扫描）"""
    params: dict = {}
    si_pid = so_pid = o_pid = oi_or_o_pid = ''
    si_cust = so_cust = o_cust = ''
    if pids:
        params['pids'] = tuple(pids)
        si_pid = _SI_PID
        so_pid = _SO_PID
        o_pid = _O_PID
        oi_or_o_pid = _OI_OR_O_PID
    if cust:
        params['sc'] = cust
        si_cust = _SI_CUST
        so_cust = _SO_CUST
        o_cust = _O_CUST
    return params, si_pid, so_pid, o_pid, oi_or_o_pid, si_cust, so_cust, o_cust


def _build_country_data_dict(country_rows: list[dict]) -> dict:
    """将国家聚合行转为 (product_id, customer) -> 'country:qty|...' 映射"""
    cdict = {}
    for row in country_rows:
        key = (row['product_id'], row['customer'])
        entry = f"{row['country']}:{row['qty']}"
        cdict[key] = (cdict.get(key, '') + '|' + entry).lstrip('|')
    return cdict


def _merge_inventory_rows(stockin_rows: list[dict], stockout_rows: list[dict],
                          order_rows: list[dict], country_rows: list[dict],
                          pnames: dict) -> list[dict]:
    """合并四张聚合查询结果为统一库存记录列表"""
    merged = {}
    for row in stockin_rows:
        key = (row['product_id'], row['customer'])
        merged[key] = dict(row)
        for fld in ('direct_stockout_qty', 'regular_stockout_qty', 'custom_stockout_qty', 'regular_order_qty', 'custom_order_qty'):
            merged[key].setdefault(fld, 0)
        merged[key].setdefault('has_order', 0)
        merged[key].setdefault('country_data', '')
    for row in stockout_rows:
        key = (row['product_id'], row['customer'])
        if key not in merged:
            merged[key] = {'stockin_qty': 0, 'has_stockin': 0, 'regular_order_qty': 0, 'custom_order_qty': 0, 'has_order': 0, 'country_data': ''}
        merged[key]['direct_stockout_qty'] = row['direct_stockout_qty']
        merged[key]['regular_stockout_qty'] = row['regular_stockout_qty']
        merged[key]['custom_stockout_qty'] = row['custom_stockout_qty']
    for row in order_rows:
        key = (row['product_id'], row['customer'])
        if key not in merged:
            merged[key] = {'stockin_qty': 0, 'has_stockin': 0, 'direct_stockout_qty': 0, 'regular_stockout_qty': 0, 'custom_stockout_qty': 0, 'country_data': ''}
        merged[key]['regular_order_qty'] = row['regular_order_qty']
        merged[key]['custom_order_qty'] = row['custom_order_qty']
        merged[key]['has_order'] = row['has_order']
    cdict = _build_country_data_dict(country_rows)
    for key in merged:
        merged[key]['country_data'] = cdict.get(key, '')
    result = []
    for key, data in merged.items():
        product_id = key[0]
        data['customer'] = key[1]
        data['product_name'] = pnames.get(product_id, {}).get('name', '')
        data['product_barcode'] = pnames.get(product_id, {}).get('barcode', '')
        result.append(data)
    return result


async def _fetch_inventory(db: AsyncSession, pids: list[int] | None, cust: str='') -> list[dict]:
    """库存聚合查询 - 优化版：无产品筛选时跳过 ANY(:pids) 避免全表扫描"""
    params, si_pid, so_pid, o_pid, oi_or_o_pid, si_cust, so_cust, o_cust = _build_inventory_query_clauses(pids, cust)
    # 安全说明：以上条件片段均为模块级常量，不含用户输入；
    # 筛选值通过 :pids/:sc 绑定参数传递。
    stockin_sql = text(f'SELECT si.product_id, si.customer, SUM(si.quantity - COALESCE(sub.consumed, 0)) AS stockin_qty, 1 AS has_stockin FROM stock_in si LEFT JOIN (  SELECT stockin_id, SUM(quantity - returned_quantity) AS consumed   FROM stock_out WHERE stockin_id IS NOT NULL{si_pid}   GROUP BY stockin_id) sub ON sub.stockin_id = si.id WHERE 1=1{si_pid}{si_cust} GROUP BY si.product_id, si.customer')  # nosec B608 — 条件片段为模块级常量，值通过绑定参数传递
    # 多 SKU：订单维度聚合改按 OrderItem；无明细订单回退订单级兼容字段（COALESCE）
    stockout_sql = text(f'SELECT so.product_id, so.customer, SUM(CASE WHEN so.order_id IS NULL THEN so.quantity - so.returned_quantity ELSE 0 END) AS direct_stockout_qty, SUM(CASE WHEN so.order_id IS NOT NULL AND (COALESCE(oi.order_type, o.order_type) IS NULL OR COALESCE(oi.order_type, o.order_type) = \'regular\') THEN so.quantity - so.returned_quantity ELSE 0 END) AS regular_stockout_qty, SUM(CASE WHEN COALESCE(oi.order_type, o.order_type) = \'custom\' THEN so.quantity - so.returned_quantity ELSE 0 END) AS custom_stockout_qty FROM stock_out so LEFT JOIN "order" o ON so.order_id = o.id LEFT JOIN order_item oi ON oi.order_id = so.order_id AND oi.product_id = so.product_id WHERE so.stockin_id IS NULL{so_pid}{so_cust} GROUP BY so.product_id, so.customer')  # nosec B608 — 条件片段为模块级常量，值通过绑定参数传递
    order_sql = text(f'SELECT COALESCE(oi.product_id, o.product_id) AS product_id, o.customer, SUM(CASE WHEN COALESCE(oi.order_type, o.order_type) IS NULL OR COALESCE(oi.order_type, o.order_type) = \'regular\' THEN COALESCE(oi.quantity, o.quantity) ELSE 0 END) AS regular_order_qty, SUM(CASE WHEN COALESCE(oi.order_type, o.order_type) = \'custom\' THEN COALESCE(oi.quantity, o.quantity) ELSE 0 END) AS custom_order_qty, 1 AS has_order FROM "order" o LEFT JOIN order_item oi ON oi.order_id = o.id WHERE 1=1{oi_or_o_pid}{o_cust} GROUP BY COALESCE(oi.product_id, o.product_id), o.customer')  # nosec B608 — 条件片段为模块级常量，值通过绑定参数传递
    country_sql = text(f'SELECT COALESCE(oi.product_id, o.product_id) AS product_id, o.customer, COALESCE(oi.country, o.country, \'常规\') AS country, SUM(COALESCE(oi.quantity, o.quantity)) AS qty FROM "order" o LEFT JOIN order_item oi ON oi.order_id = o.id WHERE COALESCE(oi.order_type, o.order_type) = \'custom\'{oi_or_o_pid}{o_cust} GROUP BY COALESCE(oi.product_id, o.product_id), o.customer, COALESCE(oi.country, o.country, \'常规\')')  # nosec B608 — 条件片段为模块级常量，值通过绑定参数传递
    stockin_rows = await _run_sql(db, stockin_sql, params)
    stockout_rows = await _run_sql(db, stockout_sql, params)
    order_rows = await _run_sql(db, order_sql, params)
    country_rows = await _run_sql(db, country_sql, params)
    # 收集实际出现的产品ID再查询名称，避免全量加载
    all_pids = set()
    for row in (*stockin_rows, *stockout_rows, *order_rows):
        all_pids.add(row['product_id'])
    pnames = await _get_prod_names(db, list(all_pids)) if all_pids else {}
    return _merge_inventory_rows(stockin_rows, stockout_rows, order_rows, country_rows, pnames)


async def _run_sql(db: AsyncSession, sql, params: dict) -> list[dict]:
    result = await db.execute(sql, params)
    cols = list(result.keys())
    return [dict(zip(cols, row, strict=False)) for row in result.all()]


async def _get_prod_names(db: AsyncSession, pids: list[int]) -> dict:
    result = await db.execute(select(Product.id, Product.name, Product.barcode).where(Product.id.in_(pids)))
    return {row[0]: {'name': row[1], 'barcode': row[2] or ''} for row in result.all()}


async def get_stock_overview_stats(db: AsyncSession) -> dict:
    """库存统计聚合（自 stock.py 端点下沉）：订单数量（常规+定制）与备货数量

    多 SKU：按 OrderItem 维度分类统计；无明细订单（批量导入兼容路径）回退
    订单级字段（COALESCE），单 SKU 订单行为与旧实现一致。
    """
    item_type = func.coalesce(OrderItem.order_type, Order.order_type)
    item_qty = func.coalesce(OrderItem.quantity, Order.quantity)
    base = (
        select(func.coalesce(func.sum(item_qty), 0))
        .select_from(Order)
        .outerjoin(OrderItem, OrderItem.order_id == Order.id)
        .where(Order.is_deleted.isnot(True))
    )
    order_regular = int((await db.execute(base.where(item_type == 'regular'))).scalar() or 0)

    order_custom = int((await db.execute(base.where(item_type == 'custom'))).scalar() or 0)

    stockin_quantity = int((await db.execute(
        select(func.coalesce(func.sum(StockIn.quantity), 0))
    )).scalar() or 0)

    return {
        'order_quantity': order_regular + order_custom,
        'order_regular_quantity': order_regular,
        'order_custom_quantity': order_custom,
        'stockin_quantity': stockin_quantity,
    }
