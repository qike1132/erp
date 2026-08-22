"""
采购计划查询与报表端点

职责：计划列表/详情、出货进度与流水、月度日历、客户汇总、库存对比、
    库存状态判定（_calc_stock_status）、出货查询回溯时间计算
    （_compute_shipment_lookback_limit）、客户图标批量填充（_enrich_customer_icon_urls）。

从 purchase_plan_crud.py 拆分而来，保持函数签名不变。
"""
import calendar
from datetime import date, datetime

from sqlalchemy import and_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only, selectinload

from fastapi_app.core.cache import cache_result
from fastapi_app.services.plan_utils import calc_shipment_status, normalize_plan_date
from fastapi_app.services.purchase_plan_inventory import _get_inventory_map
from fastapi_app.services.purchase_plan_shipment import _get_shipped_fifo_map_safe
from fastapi_app.shared_models import (
    Customer,
    Product,
    PurchasePlan,
    PurchasePlanDetail,
    StockOut,
)

# 出货记录查询回溯月数（S9: 提取为常量便于统一调整）
SHIPMENT_RECORD_LOOKBACK_MONTHS = 12


def _calc_stock_status(plan_qty: int, inventory_qty: int) -> str:
    """库存状态：充足(>=计划) / 紧张(0<库存<计划) / 无库存(库存=0)"""
    if inventory_qty <= 0:
        return 'no_stock'
    elif inventory_qty >= plan_qty:
        return 'sufficient'
    return 'shortage'


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
    shipped_fifo_map, fifo_degraded = await _get_shipped_fifo_map_safe(db, all_details, customer_name_map)
    plan_list = []
    for plan in plans:
        detail_count = len(plan.details)
        total_quantity = sum(d.quantity for d in plan.details)
        total_shipped = sum(shipped_fifo_map.get(d.id, 0) for d in plan.details)
        plan_list.append({**plan.to_dict(), 'detail_count': detail_count, 'total_quantity': total_quantity, 'total_shipped': total_shipped, 'total_remaining': total_quantity - total_shipped})
    return {'plans': plan_list, 'total': len(plan_list), 'fifo_degraded': fifo_degraded}

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
    shipped_fifo_map, _fifo_degraded = await _get_shipped_fifo_map_safe(db, details, customer_name_map)
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
    shipped_fifo_map, fifo_degraded = await _get_shipped_fifo_map_safe(db, details, customer_name_map)
    progress_list = []
    for d in details:
        shp_qty = shipped_fifo_map.get(d.id, 0)
        remaining = d.quantity - shp_qty
        percent = round(shp_qty / d.quantity * 100, 1) if d.quantity > 0 else 0
        progress_list.append({'detail_id': d.id, 'product_name': d.product_name, 'barcode': d.barcode, 'plan_qty': d.quantity, 'shipped_qty': shp_qty, 'remaining_qty': remaining, 'percent': percent, 'shipment_status': calc_shipment_status(d.quantity, shp_qty)})
    return {'details': progress_list, 'fifo_degraded': fifo_degraded}

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
    _sql = """
        SELECT d.id AS detail_id, d.plan_id, p.customer_id, p.customer_name,
               d.product_name, d.barcode, d.plan_date, d.quantity
        FROM purchase_plan_details d
        JOIN purchase_plans p ON d.plan_id = p.id
        WHERE p.plan_month = :plan_month
    """ + (" AND p.customer_id = :customer_id" if customer_id else "")  # nosec B608
    sql = text(_sql)

    params: dict = {'plan_month': plan_month}
    if customer_id:
        params['customer_id'] = customer_id

    result = await db.execute(sql, params)
    rows = result.all()

    detail_shipped_map: dict[int, int] = {}
    fifo_degraded = False
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
        shipped_fifo_map, fifo_degraded = await _get_shipped_fifo_map_safe(db, all_details, customer_name_map, plan_month=plan_month)
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

    return {'year': year, 'month': month, 'days_in_month': days_in_month, 'plans_by_date': plans_by_date, 'customers': await _enrich_customer_icon_urls(db, list(customer_set.values())), 'fifo_degraded': fifo_degraded}


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
    shipped_fifo_map, fifo_degraded = await _get_shipped_fifo_map_safe(db, all_details, customer_name_map, plan_month=plan_month)
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
    return {'customers': list(summary.values()), 'total_plan_qty': sum(s['plan_qty'] for s in summary.values()), 'total_inventory_qty': sum(s['inventory_qty'] for s in summary.values()), 'total_shipped_qty': sum(s['shipped_qty'] for s in summary.values()), 'total_remaining_qty': sum(s['remaining_qty'] for s in summary.values()), 'warning_count': sum(s['warning_count'] for s in summary.values()), 'fifo_degraded': fifo_degraded}


# 星期缩写（与前端 WDS 对齐，index by JS getDay(): Sunday=0..Saturday=6）
_PP_WDS = ['日', '一', '二', '三', '四', '五', '六']


def _py_weekday_to_js(py_wd: int) -> str:
    """Python weekday()(Mon=0..Sun=6) → 前端 WDS 字符串(Sun=0..Sat=6)"""
    return _PP_WDS[(py_wd + 1) % 7]


@cache_result(
    key_prefix="pp:agg",
    ttl=120,
    local_ttl=30,
    key_builder=lambda **kwargs: f"v1:y{kwargs.get('year', 0)}:m{kwargs.get('month', 0)}:c{kwargs.get('customer_id', 0)}",
)
async def get_monthly_aggregated(db: AsyncSession, year: int, month: int, customer_id: int=0) -> dict:
    """月度聚合数据：在后端完成 rows + sku_summary + sku_date_index + customers 聚合，
    避免向前端传输 20K+ 明细并在前端聚合（6.9 + 6.10）。

    返回结构:
      rows: 按日期聚合的列表（不含明细 plans）
      sku_summary: 按 customer|product 聚合的 SKU 列表
      sku_date_index: {customer|product: [{date,day,weekday,qty,customer,status}]}
      customers: 客户汇总列表（合并原 customer-summary 逻辑）
      customer_totals: 客户汇总总量
    """
    plan_month = f'{year}-{month:02d}'
    days_in_month = calendar.monthrange(year, month)[1]

    _sql = """
        SELECT d.id AS detail_id, d.plan_id, p.customer_id, p.customer_name,
               d.product_name, d.barcode, d.plan_date, d.quantity
        FROM purchase_plan_details d
        JOIN purchase_plans p ON d.plan_id = p.id
        WHERE p.plan_month = :plan_month
    """ + (" AND p.customer_id = :customer_id" if customer_id else "")  # nosec B608
    sql = text(_sql)

    params: dict = {'plan_month': plan_month}
    if customer_id:
        params['customer_id'] = customer_id

    result = await db.execute(sql, params)
    rows = result.all()

    detail_shipped_map: dict[int, int] = {}
    fifo_degraded = False
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
        customer_name_map: dict[int, str] = {}
        for row in rows:
            if row.plan_id not in customer_name_map:
                customer_name_map[row.plan_id] = row.customer_name
        shipped_fifo_map, fifo_degraded = await _get_shipped_fifo_map_safe(db, all_details, customer_name_map, plan_month=plan_month)
        detail_shipped_map = {d.id: shipped_fifo_map.get(d.id, 0) for d in all_details}

    inventory_map = await _get_inventory_map(db)

    # ---- 单次遍历完成全部聚合 ----
    by_date: dict[str, dict] = {}
    by_key: dict[str, dict] = {}
    _prod_cust_date_map: dict[str, dict[str, dict]] = {}
    product_summary: dict[tuple, dict] = {}

    for row in rows:
        dt = row.plan_date
        date_str = dt.isoformat() if dt else ''
        shp_qty = detail_shipped_map.get(row.detail_id, 0)
        qty = row.quantity
        remain = qty - shp_qty
        status = 'completed' if shp_qty >= qty else ('partial' if shp_qty > 0 else 'pending')
        customer_name = row.customer_name or '未知客户'
        product_name = row.product_name or '—'
        py_wd = dt.weekday() if dt else 0

        # 日期聚合
        if date_str not in by_date:
            by_date[date_str] = {
                'date': date_str, 'day_num': dt.day if dt else 0,
                'weekday': _py_weekday_to_js(py_wd),
                '_cust_set': set(), 'plan_count': 0, 'total_qty': 0,
                'shipped_qty': 0, 'shipped_count': 0, 'pending_count': 0,
            }
        d = by_date[date_str]
        d['_cust_set'].add(customer_name)
        d['plan_count'] += 1
        d['total_qty'] += qty
        d['shipped_qty'] += shp_qty
        if status == 'completed':
            d['shipped_count'] += 1
        else:
            d['pending_count'] += 1

        # SKU 聚合
        sku_key = f'{customer_name}|{product_name}'
        if sku_key not in by_key:
            by_key[sku_key] = {'barcode': row.barcode or '—', 'product_name': product_name,
                               'plan_qty': 0, 'shipped_qty': 0, 'remain_qty': 0, 'customer_name': customer_name}
        sk = by_key[sku_key]
        sk['plan_qty'] += qty
        sk['shipped_qty'] += shp_qty
        sk['remain_qty'] += remain

        # SKU 日期索引
        if sku_key not in _prod_cust_date_map:
            _prod_cust_date_map[sku_key] = {}
        date_map = _prod_cust_date_map[sku_key]
        if date_str not in date_map:
            date_map[date_str] = {'date': date_str, 'day': dt.day if dt else 0,
                                  'weekday': _py_weekday_to_js(py_wd),
                                  'qty': 0, 'customer': customer_name, 'status': status}
        date_map[date_str]['qty'] += qty

        # 客户汇总（产品级）
        inv_qty = inventory_map.get((customer_name, product_name), 0)
        product_key = (row.customer_id, product_name)
        if product_key not in product_summary:
            product_summary[product_key] = {'customer_id': row.customer_id, 'customer_name': customer_name,
                                            'plan_qty': 0, 'inventory_qty': inv_qty, 'shipped_qty': 0,
                                            'remaining_qty': 0, 'warning': False}
        ps = product_summary[product_key]
        ps['plan_qty'] += qty
        ps['shipped_qty'] += shp_qty
        ps['remaining_qty'] += remain
        if _calc_stock_status(qty, inv_qty) != 'sufficient':
            ps['warning'] = True

    # 构建 rows 列表（字段名与前端 Row 类型对齐）
    rows_list = []
    for date_str, d in by_date.items():
        rows_list.append({
            'date': date_str, '_dayNum': d['day_num'], '_weekday': d['weekday'],
            'customerCount': len(d['_cust_set']), 'planCount': d['plan_count'],
            'totalQty': d['total_qty'], '_shippedCount': d['shipped_count'],
            '_pendingCount': d['pending_count'],
            '_shippedPct': int(d['shipped_qty'] / d['total_qty'] * 1000) / 10 if d['total_qty'] > 0 else 0,
            'customerNames': sorted(d['_cust_set']),
            '_fullDate': f'{month}月{d["day_num"]}日', '_isPeak': False,
        })
    rows_list.sort(key=lambda r: r['date'])
    max_plan = max((r['planCount'] for r in rows_list), default=0)
    for r in rows_list:
        r['_isPeak'] = r['planCount'] == max_plan and max_plan > 0

    # sku_summary 列表（字段名与前端 SkuRow 类型对齐）
    sku_summary = []
    for sk in by_key.values():
        sku_summary.append({
            'barcode': sk['barcode'], 'product_name': sk['product_name'],
            'plan_qty': sk['plan_qty'], 'shipped_qty': sk['shipped_qty'],
            'remain_qty': sk['remain_qty'], 'customer_name': sk['customer_name'],
            '_pct': int(sk['shipped_qty'] / sk['plan_qty'] * 1000) / 10 if sk['plan_qty'] > 0 else 0,
            '_odd': False,
        })
    sku_summary.sort(key=lambda s: (s['customer_name'], s['barcode']))

    # sku_date_index
    sku_date_index = {}
    for k, dm in _prod_cust_date_map.items():
        sku_date_index[k] = sorted(dm.values(), key=lambda x: x['date'])

    # 客户汇总
    summary: dict[int, dict] = {}
    for ps in product_summary.values():
        cid = ps['customer_id']
        if cid not in summary:
            summary[cid] = {'customer_id': cid, 'customer_name': ps['customer_name'],
                            'plan_qty': 0, 'inventory_qty': 0, 'shipped_qty': 0,
                            'remaining_qty': 0, 'warning_count': 0}
        s = summary[cid]
        s['plan_qty'] += ps['plan_qty']
        s['inventory_qty'] += ps['inventory_qty']
        s['shipped_qty'] += ps['shipped_qty']
        s['remaining_qty'] += ps['remaining_qty']
        if ps['warning']:
            s['warning_count'] += 1
    customers = list(summary.values())
    customer_totals = {
        'total_plan_qty': sum(s['plan_qty'] for s in customers),
        'total_inventory_qty': sum(s['inventory_qty'] for s in customers),
        'total_shipped_qty': sum(s['shipped_qty'] for s in customers),
        'total_remaining_qty': sum(s['remaining_qty'] for s in customers),
        'warning_count': sum(s['warning_count'] for s in customers),
    }

    return {
        'year': year, 'month': month, 'days_in_month': days_in_month,
        'rows': rows_list, 'sku_summary': sku_summary, 'sku_date_index': sku_date_index,
        'customers': customers, 'customer_totals': customer_totals, 'fifo_degraded': fifo_degraded,
    }


@cache_result(
    key_prefix="pp:day",
    ttl=120,
    local_ttl=30,
    key_builder=lambda **kwargs: f"v1:y{kwargs.get('year', 0)}:m{kwargs.get('month', 0)}:d{kwargs.get('day', 0)}:c{kwargs.get('customer_id', 0)}",
)
async def get_day_details(db: AsyncSession, year: int, month: int, day: int, customer_id: int=0) -> dict:
    """指定日期的明细列表（按需加载，供日期详情弹窗使用，避免全量传输）"""
    plan_month = f'{year}-{month:02d}'
    target_date = date(year, month, day)
    date_str = target_date.isoformat()

    _sql = """
        SELECT d.id AS detail_id, d.plan_id, p.customer_id, p.customer_name,
               d.product_name, d.barcode, d.plan_date, d.quantity
        FROM purchase_plan_details d
        JOIN purchase_plans p ON d.plan_id = p.id
        WHERE p.plan_month = :plan_month AND d.plan_date = :plan_date
    """ + (" AND p.customer_id = :customer_id" if customer_id else "")  # nosec B608
    sql = text(_sql)

    params: dict = {'plan_month': plan_month, 'plan_date': target_date}
    if customer_id:
        params['customer_id'] = customer_id

    result = await db.execute(sql, params)
    rows = result.all()

    detail_shipped_map: dict[int, int] = {}
    fifo_degraded = False
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
        )
        all_details = detail_result.scalars().all()
        customer_name_map: dict[int, str] = {}
        for row in rows:
            if row.plan_id not in customer_name_map:
                customer_name_map[row.plan_id] = row.customer_name
        shipped_fifo_map, fifo_degraded = await _get_shipped_fifo_map_safe(db, all_details, customer_name_map, plan_month=plan_month)
        detail_shipped_map = {d.id: shipped_fifo_map.get(d.id, 0) for d in all_details}

    plans = []
    by_customer: dict[str, list] = {}
    total_qty = 0
    shipped_qty = 0
    for row in rows:
        shp = detail_shipped_map.get(row.detail_id, 0)
        qty = row.quantity
        plan = {
            'detail_id': row.detail_id, 'plan_id': row.plan_id,
            'customer_name': row.customer_name, 'product_name': row.product_name,
            'barcode': row.barcode, 'quantity': qty, 'shipped_qty': shp,
            'remaining_qty': qty - shp, 'plan_date': date_str,
        }
        plans.append(plan)
        cn = row.customer_name or '未知'
        if cn not in by_customer:
            by_customer[cn] = []
        by_customer[cn].append(plan)
        total_qty += qty
        shipped_qty += shp

    return {
        'date': date_str, 'weekday': _py_weekday_to_js(target_date.weekday()),
        'plans': plans, 'by_customer': by_customer,
        'shipped_pct': int(shipped_qty / total_qty * 1000) / 10 if total_qty > 0 else 0,
        'fifo_degraded': fifo_degraded,
    }


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
