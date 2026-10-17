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
from fastapi_app.shared_models import DailyProductionRecord, FinishedStockRemark, Product, StockOut

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
            func.coalesce(FinishedStockRemark.remark, '').label('remark'),
        )
        .select_from(bi)
        .outerjoin(
            bo,
            (bo.c.product_id == bi.c.product_id) & (bo.c.batch_no == bi.c.batch_no),
        )
        .outerjoin(Product, Product.id == bi.c.product_id)
        # 备注键只含 (产品,批次)：customer_name 是派生展示值，批次客户构成变化会抖动，
        # 拿它当关联键会让备注静默失联（单客户塌成 '' 后 ON 条件匹配不上）
        .outerjoin(
            FinishedStockRemark,
            (FinishedStockRemark.product_id == bi.c.product_id)
            & (FinishedStockRemark.batch_no == bi.c.batch_no),
        )
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
            'remark': r['remark'] or '',
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
    """客户快捷切换栏客户列表。

    复用 /stock 的同一口径（``stock_inventory_service._get_all_customers``）：
    成员 = 出现在 stock_in 或「未软删 order」里的客户，按最近活动排序。
    不读 daily_production_record：包装部录入的客户可能为空（存量大量未填），
    用它会让 chips 时有时无；且 /stock 的客户源更完整、两页观感一致。
    """
    from fastapi_app.services.stock_inventory_service import _get_all_customers as _stock_customers

    return await _stock_customers(db, None)


async def get_batches_by_product(
    db: AsyncSession,
    product_id: int,
    customer_name: str = '',
) -> list[dict]:
    """某产品的批次可用量列表（供 /stock-out 录入 SKU 后带出批次选择）。

    批次可用是 (产品, 批次) 级事实，与客户无关：``customer_name`` 仅为兼容既有
    API 签名而保留，**不参与过滤**（原因见下方注释）。

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
    # 不按客户过滤：bi.c.customer_name 是展示值，只要该批次有任何一条无客户的生产记录
    # 或多客户就会塌成 ''，按它过滤会把出货闸门（get_batch_available 本就与客户无关）
    # 会放行的批次藏掉 —— 那批货于是走「不指定批次」出货，批次行永远不被扣减、数字虚高。
    # 批次可用是 (产品, 批次) 级事实，见模块 docstring。
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


async def upsert_remark(
    db: AsyncSession, *, customer_name: str = '', product_id: int, batch_no: str, remark: str,
) -> None:
    """页面级备注 UPSERT：键 (产品,批次) 一行一条；内容清空则删行。

    ``customer_name`` 仅为兼容既有 API 签名而保留，只作展示快照存档，
    **不参与关联**（它是派生展示值，会随批次客户构成抖动）。
    用 PG 的 INSERT ... ON CONFLICT DO UPDATE（唯一索引 uq_fs_remark_prod_batch
    兜底），避免「先查后写」的并发竞态；空备注走 DELETE，不留空行。
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    bno = (batch_no or '').strip()
    text = (remark or '').strip()

    if not text:
        from sqlalchemy import delete
        await db.execute(
            delete(FinishedStockRemark).where(
                FinishedStockRemark.product_id == product_id,
                FinishedStockRemark.batch_no == bno,
            )
        )
        return

    stmt = pg_insert(FinishedStockRemark).values(
        customer_name=(customer_name or '').strip(), product_id=product_id, batch_no=bno, remark=text,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=['product_id', 'batch_no'],
        set_={'remark': text, 'updated_at': func.now()},
    )
    await db.execute(stmt)
