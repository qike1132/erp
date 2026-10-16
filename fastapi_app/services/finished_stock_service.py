"""成品库存（批次级）只读聚合服务

口径（与 /stock 同源，见 docs 方案 §一）：
- 入库 = daily_production_record WHERE department='packaging' AND product_id IS NOT NULL
- 出货 = stock_out WHERE stockin_id IS NULL（排除备货抵扣行）按 (product_id, batch_no) 汇总
- 批次可用 = 批次入库 − 该批次已出货（退货经 returned_quantity 回补）

产品级结余闸门（get_inventory_balance）不变，本服务只在其上叠加批次维度，
不产生第二真相源。批次可用是 (产品,批次) 级事实：入库/出货都按 (产品,批次) 聚合，
客户只作展示（该批次入库行同属一个客户则显示其名，跨客户显示 '' 未指定），
故同一 (产品,批次) 跨客户也不会重复扣减。
"""
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.sanitizer import escape_like
from fastapi_app.shared_models import DailyProductionRecord, Product, StockOut

PACKAGING = 'packaging'


def _batch_in_subq():
    """入库聚合：按 (产品, 批次) 分组。

    批次可用是 (产品,批次) 级事实——一个批次号编码一次生产，出货也按批次扣减；
    故**不**按客户拆行：若同一 (产品,批次) 有多个客户的入库行，拆行会让出货量在
    每行重复扣减（'' 桶承载全部存量数据，尤其常见）。
    客户只作展示：该批次入库行同属一个客户时显示该客户名，跨客户则显示 ''（未指定）。
    """
    batch_key = func.coalesce(DailyProductionRecord.batch_no, '')
    cust = func.coalesce(DailyProductionRecord.customer_name, '')
    display_cust = case((func.count(func.distinct(cust)) == 1, func.max(cust)), else_='')
    return (
        select(
            display_cust.label('customer_name'),
            DailyProductionRecord.product_id.label('product_id'),
            func.max(DailyProductionRecord.product_name).label('product_name'),
            func.max(DailyProductionRecord.barcode).label('barcode'),
            batch_key.label('batch_no'),
            func.bool_or(DailyProductionRecord.is_custom).label('is_custom'),
            func.max(DailyProductionRecord.custom_country).label('custom_country'),
            func.sum(DailyProductionRecord.quantity).label('batch_in_qty'),
        )
        .where(
            DailyProductionRecord.department == PACKAGING,
            DailyProductionRecord.product_id.isnot(None),
        )
        .group_by(DailyProductionRecord.product_id, batch_key)
        .subquery()
    )


def _batch_out_subq():
    """出货聚合：按 (产品, 批次) 分组，排除备货抵扣行。

    不过滤 batch_no IS NULL：无批次出货（默认「不指定批次」路径 + 全部存量行）仍消耗
    产品级库存，必须落进 ''（未分批次）桶，否则该桶只减入库不减出货、可用量虚高。
    """
    batch_key = func.coalesce(StockOut.batch_no, '')
    return (
        select(
            StockOut.product_id.label('product_id'),
            batch_key.label('batch_no'),
            func.sum(StockOut.quantity - StockOut.returned_quantity).label('batch_out_qty'),
        )
        .where(StockOut.stockin_id.is_(None))
        .group_by(StockOut.product_id, batch_key)
        .subquery()
    )


async def get_finished_stock_summary(
    db: AsyncSession,
    *,
    customer_name: str = '',
    product_search: str = '',
    batch_no: str = '',
    page: int = 1,
    per_page: int = 20,
) -> dict:
    """按 客户/产品/批次 聚合成品库存。

    Returns:
        dict: {data, total, page, per_page, all_customers}
        data 每项：customer_name/product_name/barcode/batch_no/
                   batch_in_qty/batch_available/is_custom/custom_country
    """
    bi = _batch_in_subq()
    bo = _batch_out_subq()

    available = (bi.c.batch_in_qty - func.coalesce(bo.c.batch_out_qty, 0)).label('batch_available')

    base = (
        select(
            bi.c.customer_name,
            bi.c.product_id,
            bi.c.product_name,
            bi.c.barcode,
            bi.c.batch_no,
            bi.c.is_custom,
            bi.c.custom_country,
            bi.c.batch_in_qty,
            available,
            Product.image.label('image'),
        )
        .select_from(bi)
        .outerjoin(
            bo,
            (bo.c.product_id == bi.c.product_id) & (bo.c.batch_no == bi.c.batch_no),
        )
        .outerjoin(Product, Product.id == bi.c.product_id)
    )

    conditions = []
    if customer_name:
        conditions.append(func.coalesce(bi.c.customer_name, '') == customer_name)
    if batch_no:
        conditions.append(bi.c.batch_no == batch_no)
    if product_search:
        like = f'%{escape_like(product_search)}%'
        conditions.append(or_(bi.c.product_name.ilike(like), bi.c.barcode.ilike(like)))
    if conditions:
        base = base.where(*conditions)

    base = base.order_by(
        func.coalesce(bi.c.customer_name, ''),
        bi.c.product_name,
        bi.c.batch_no,
    )

    # 全量（过滤后、未分页）的行数与可用库存合计：页面顶部汇总要的是全量值，
    # 不能拿当前页的行求和（翻页/筛选会让数字跳动）。
    count_sq = base.order_by(None).subquery()
    agg = (await db.execute(
        select(
            func.count().label('total'),
            func.coalesce(func.sum(count_sq.c.batch_available), 0).label('total_available'),
        ).select_from(count_sq)
    )).one()
    total = int(agg.total or 0)
    total_available = int(agg.total_available or 0)

    rows = (await db.execute(base.limit(per_page).offset((page - 1) * per_page))).mappings().all()
    data = [
        {
            'customer_name': r['customer_name'] or '',
            'product_id': r['product_id'],
            'product_name': r['product_name'] or '',
            'barcode': r['barcode'] or '',
            'batch_no': r['batch_no'] or '',
            'image': r['image'] or '',
            'batch_in_qty': int(r['batch_in_qty'] or 0),
            'batch_available': int(r['batch_available'] or 0),
            'is_custom': bool(r['is_custom']),
            'custom_country': r['custom_country'] or '',
        }
        for r in rows
    ]

    all_customers = await _get_all_customers(db)
    return {
        'data': data,
        'total': int(total),
        'total_available': total_available,
        'page': page,
        'per_page': per_page,
        'all_customers': all_customers,
    }


async def _get_all_customers(db: AsyncSession) -> list[str]:
    """成品库存里出现过的客户名（含未指定客户 → ''），供页面快捷切换。"""
    col = func.coalesce(DailyProductionRecord.customer_name, '')
    rows = (
        await db.execute(
            select(col)
            .where(
                DailyProductionRecord.department == PACKAGING,
                DailyProductionRecord.product_id.isnot(None),
            )
            .distinct()
            .order_by(col)
        )
    ).scalars().all()
    return [c for c in rows if c]


async def get_batches_by_product(
    db: AsyncSession,
    product_id: int,
    customer_name: str = '',
) -> list[dict]:
    """某产品的批次可用量列表（供 /stock-out 录入 SKU 后带出批次选择）。

    Returns: [{batch_no, available_quantity}]，按批次号升序（= 生产时间正序）。
    """
    bi = _batch_in_subq()
    bo = _batch_out_subq()
    available = (bi.c.batch_in_qty - func.coalesce(bo.c.batch_out_qty, 0)).label('available_quantity')

    q = (
        select(bi.c.batch_no, available)
        .select_from(bi)
        .outerjoin(bo, (bo.c.product_id == bi.c.product_id) & (bo.c.batch_no == bi.c.batch_no))
        .where(bi.c.product_id == product_id)
        # 只返回真实批次；空批次（未分批次）不可选，不进下拉
        .where(bi.c.batch_no != '')
    )
    if customer_name:
        q = q.where(func.coalesce(bi.c.customer_name, '') == customer_name)
    q = q.order_by(bi.c.batch_no)

    rows = (await db.execute(q)).mappings().all()
    return [
        {'batch_no': r['batch_no'] or '', 'available_quantity': int(r['available_quantity'] or 0)}
        for r in rows
    ]


async def get_batch_available(db: AsyncSession, product_id: int, batch_no: str) -> int:
    """单批次可用量（出货批次级扣减闸门用）。

    复用 summary 同一组子查询与同一 join，避免两处口径漂移。
    无匹配入库行 → 0（该批次没生产过，闸门自然拒绝）。
    """
    bi = _batch_in_subq()
    bo = _batch_out_subq()
    q = (
        select((bi.c.batch_in_qty - func.coalesce(bo.c.batch_out_qty, 0)).label('available'))
        .select_from(bi)
        .outerjoin(bo, (bo.c.product_id == bi.c.product_id) & (bo.c.batch_no == bi.c.batch_no))
        .where(bi.c.product_id == product_id, bi.c.batch_no == batch_no)
    )
    row = (await db.execute(q)).first()
    return int(row[0] or 0) if row is not None else 0
