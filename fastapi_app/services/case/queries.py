"""皮套查询域(搜索/列表/汇总/流水/详情)

从 case_service.py 按职责拆出,行为与原实现完全一致。
"""
import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from fastapi_app.core.exceptions import NotFoundError
from fastapi_app.core.sanitizer import escape_like
from fastapi_app.services.case._common import (
    DEFAULT_SEARCH_LIMIT,
    MAX_LIST_PAGE_SIZE,
    MAX_SUMMARY_PAGE_SIZE,
    _apply_date_filter,
    _apply_quantity_filter,
    _normalize_pagination,
)
from fastapi_app.services.case._serializers import _serialize_stockin, _serialize_stockout
from fastapi_app.shared_models import Case, CaseInventoryLog, CaseStockIn, CaseStockOut, Product
from fastapi_app.utils import calc_total_pages

logger = logging.getLogger(__name__)


async def search_cases(db: AsyncSession, query: str = '') -> list[dict]:
    """搜索皮套（附库存信息）。

    支持按产品名称或条码模糊匹配；未提供关键词时返回最多 20 条记录。

    Args:
        db: 异步数据库会话。
        query: 搜索关键词，匹配 Product.name 或 Product.barcode，空字符串表示返回前 20 条。

    Returns:
        皮套字典列表，每项包含 id、name、barcode、current_stock 字段。
    """
    q = select(Product).outerjoin(Case, Product.id == Case.product_id).options(
        joinedload(Product.cases)
    )
    if query:
        q = q.where(
            Product.name.like(f'%{escape_like(query)}%')  # sql-safe: escape_like/绑定参数/常量片段
            | Product.barcode.like(f'%{escape_like(query)}%')  # sql-safe: escape_like/绑定参数/常量片段
        )
    else:
        q = q.limit(DEFAULT_SEARCH_LIMIT)

    result = await db.execute(q)
    products = list(result.unique().scalars().all())

    return [{
        'id': p.id,
        'name': p.name,
        'barcode': p.barcode or '',
        'current_stock': p.cases[0].current_stock if p.cases else 0,
    } for p in products]

async def get_case_stockins(db: AsyncSession, page: int = 1, per_page: int = 20, customer: str = '',
                             start_date: str = '', end_date: str = '',
                             quantity_min: int | None = None, quantity_max: int | None = None) -> dict:
    """获取皮套入库列表（分页）。

    支持按客户、日期范围、数量范围过滤。

    Args:
        db: 异步数据库会话。
        page: 页码，从 1 开始。
        per_page: 每页数量，1-100。
        customer: 客户名称模糊匹配，空字符串表示不限制。
        start_date: 开始日期（YYYY-MM-DD），空字符串表示不限制。
        end_date: 结束日期（YYYY-MM-DD，含当天），空字符串表示不限制。
        quantity_min: 最小数量（含），None 表示不限制。
        quantity_max: 最大数量（含），None 表示不限制。

    Returns:
        dict，包含 stockins（入库列表）、total（总数）、pages（总页数）、current_page（当前页码）。
    """
    page, per_page = _normalize_pagination(page, per_page, MAX_LIST_PAGE_SIZE)
    query = select(CaseStockIn).options(joinedload(CaseStockIn.case).joinedload(Case.product))

    if customer:
        query = query.where(CaseStockIn.customer.like(f'%{escape_like(customer)}%'))  # sql-safe: escape_like/绑定参数/常量片段
    query = _apply_date_filter(query, CaseStockIn.stockin_date, start_date, end_date, '开始日期')
    query = _apply_quantity_filter(query, CaseStockIn.quantity, quantity_min, quantity_max)

    # 总数
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    query = query.order_by(CaseStockIn.stockin_date.desc())
    offset = (page - 1) * per_page
    query = query.offset(offset).limit(per_page)
    result = await db.execute(query)
    stockins = list(result.unique().scalars().all())

    return {
        'stockins': [_serialize_stockin(s) for s in stockins],
        'total': total,
        'pages': calc_total_pages(total, per_page),
        'current_page': page,
    }

async def get_case_stockout_list(db: AsyncSession, page: int = 1, per_page: int = 20, customer: str = '',
                                 start_date: str = '', end_date: str = '',
                                 quantity_min: int | None = None, quantity_max: int | None = None) -> dict:
    """获取皮套出库列表（分页）。

    支持按客户、日期范围、数量范围过滤。

    Args:
        db: 异步数据库会话。
        page: 页码，从 1 开始。
        per_page: 每页数量，1-100。
        customer: 客户名称模糊匹配，空字符串表示不限制。
        start_date: 开始日期（YYYY-MM-DD），空字符串表示不限制。
        end_date: 结束日期（YYYY-MM-DD，含当天），空字符串表示不限制。
        quantity_min: 最小数量（含），None 表示不限制。
        quantity_max: 最大数量（含），None 表示不限制。

    Returns:
        dict，包含 stockouts（出库列表）、total（总数）、pages（总页数）、current_page（当前页码）。
    """
    page, per_page = _normalize_pagination(page, per_page, MAX_LIST_PAGE_SIZE)
    query = select(CaseStockOut).options(joinedload(CaseStockOut.case).joinedload(Case.product))

    if customer:
        query = query.where(CaseStockOut.customer.like(f'%{escape_like(customer)}%'))  # sql-safe: escape_like/绑定参数/常量片段
    query = _apply_date_filter(query, CaseStockOut.stockout_date, start_date, end_date, '开始日期')
    query = _apply_quantity_filter(query, CaseStockOut.quantity, quantity_min, quantity_max)

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    query = query.order_by(CaseStockOut.stockout_date.desc())
    offset = (page - 1) * per_page
    query = query.offset(offset).limit(per_page)
    result = await db.execute(query)
    stockouts = list(result.unique().scalars().all())

    return {
        'stockouts': [_serialize_stockout(s) for s in stockouts],
        'total': total,
        'pages': calc_total_pages(total, per_page),
        'current_page': page,
    }

def _build_inventory_base_query(in_sq, out_sq, search: str):
    """构建库存汇总基础查询（含搜索条件）。

    Args:
        in_sq: 入库聚合子查询。
        out_sq: 出库聚合子查询。
        search: 搜索关键词，空字符串表示不限制。

    Returns:
        SQLAlchemy 查询对象。
    """
    base_q = select(
        Case,
        func.coalesce(in_sq.c.total_in, 0).label('total_in'),
        func.coalesce(out_sq.c.total_out, 0).label('total_out'),
    ) \
        .outerjoin(in_sq, Case.id == in_sq.c.case_id) \
        .outerjoin(out_sq, Case.id == out_sq.c.case_id)

    if search:
        search_pattern = f'%{escape_like(search)}%'
        base_q = base_q.outerjoin(Product, Case.product_id == Product.id).where(
            Case.name.like(search_pattern) | Case.barcode.like(search_pattern)
            | Product.name.like(search_pattern) | Product.barcode.like(search_pattern)
        )
    return base_q

def _build_inventory_items(result) -> list[dict]:
    """从查询结果构建库存列表项，过滤无任何流水的空记录。

    Args:
        result: SQLAlchemy 查询结果迭代器。

    Returns:
        库存字典列表。
    """
    data = []
    for case_obj, total_in, total_out in result.all():
        calc_stock = int(total_in or 0) - int(total_out or 0)
        # 过滤无任何入库/出库流水的空记录
        if total_in == 0 and total_out == 0 and calc_stock == 0:
            continue
        data.append({
            'id': case_obj.id, 'name': case_obj.sync_name, 'barcode': case_obj.sync_barcode or '',
            'initial_stock': case_obj.initial_stock, 'current_stock': calc_stock,
            'total_in': int(total_in or 0), 'total_out': int(total_out or 0),
        })
    return data

async def _compute_inventory_stats(db: AsyncSession, in_sq, out_sq, search: str) -> dict:
    """计算库存整体统计（总入库、总出库、总库存）。

    Args:
        db: 异步数据库会话。
        in_sq: 入库聚合子查询。
        out_sq: 出库聚合子查询。
        search: 搜索关键词（需与主查询保持一致）。

    Returns:
        dict，包含 total_stock、total_in、total_out 字段。
    """
    stats_q = select(
        func.coalesce(func.sum(in_sq.c.total_in), 0),
        func.coalesce(func.sum(out_sq.c.total_out), 0),
    ).select_from(Case) \
        .outerjoin(in_sq, Case.id == in_sq.c.case_id) \
        .outerjoin(out_sq, Case.id == out_sq.c.case_id)
    if search:
        search_pattern = f'%{escape_like(search)}%'
        stats_q = stats_q.outerjoin(Product, Case.product_id == Product.id).where(
            Case.name.like(search_pattern) | Case.barcode.like(search_pattern)
            | Product.name.like(search_pattern) | Product.barcode.like(search_pattern)
        )
    sum_in, sum_out = (await db.execute(stats_q)).one()
    return {
        'total_stock': int(sum_in or 0) - int(sum_out or 0),
        'total_in': int(sum_in or 0),
        'total_out': int(sum_out or 0),
    }

async def get_case_inventory_summary(db: AsyncSession, page: int = 1, per_page: int = 50, search: str = '') -> dict:
    """获取皮套库存汇总（分页）。

    通过聚合入库/出库记录计算每个皮套的当前库存，并返回整体统计。

    Args:
        db: 异步数据库会话。
        page: 页码，从 1 开始。
        per_page: 每页数量，1-200。
        search: 搜索关键词，匹配 Case.name、Case.barcode、Product.name、Product.barcode。

    Returns:
        dict，包含 inventory（库存列表）、total（总数）、page、per_page、pages、stats（整体统计）。
    """
    page, per_page = _normalize_pagination(page, per_page, MAX_SUMMARY_PAGE_SIZE)

    in_sq = select(CaseStockIn.case_id, func.sum(CaseStockIn.quantity).label('total_in')).group_by(CaseStockIn.case_id).subquery()
    out_sq = select(CaseStockOut.case_id, func.sum(CaseStockOut.quantity).label('total_out')).group_by(CaseStockOut.case_id).subquery()

    base_q = _build_inventory_base_query(in_sq, out_sq, search)
    # count_q 需应用与 _build_inventory_items 相同的过滤条件（排除无任何入库/出库流水的空记录）
    base_subq = base_q.subquery()
    count_q = select(func.count()).select_from(base_subq).where(
        (base_subq.c.total_in != 0)
        | (base_subq.c.total_out != 0)
    )
    total = (await db.execute(count_q)).scalar() or 0

    offset = (page - 1) * per_page
    paged_q = base_q.order_by(Case.id).offset(offset).limit(per_page)
    result = await db.execute(paged_q)

    data = _build_inventory_items(result)
    stats = await _compute_inventory_stats(db, in_sq, out_sq, search)

    return {
        'inventory': data,
        'total': total,
        'page': page,
        'per_page': per_page,
        'pages': calc_total_pages(total, per_page),
        'stats': stats,
    }

async def get_case_inventory_logs(db: AsyncSession, case_id: int, page: int = 1, per_page: int = 20,
                                   log_type: str = '', start_date: str = '', end_date: str = '') -> dict:
    """获取皮套库存流水（分页）。

    Args:
        db: 异步数据库会话。
        case_id: 皮套 ID。
        page: 页码，从 1 开始。
        per_page: 每页数量，1-100。
        log_type: 流水类型过滤（如"入库"、"出库"），空字符串表示不限制。
        start_date: 开始日期（YYYY-MM-DD），空字符串表示不限制。
        end_date: 结束日期（YYYY-MM-DD，含当天），空字符串表示不限制。

    Returns:
        dict，包含 success、logs（流水列表）、pagination（分页信息）。
    """
    page, per_page = _normalize_pagination(page, per_page, MAX_LIST_PAGE_SIZE)
    query = select(CaseInventoryLog).where(CaseInventoryLog.case_id == case_id)

    if log_type:
        query = query.where(CaseInventoryLog.change_type == log_type)
    query = _apply_date_filter(query, CaseInventoryLog.change_date, start_date, end_date, '开始日期')

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    query = query.order_by(CaseInventoryLog.change_date.desc())
    offset = (page - 1) * per_page
    query = query.offset(offset).limit(per_page)
    result = await db.execute(query)
    logs = list(result.scalars().all())

    return {
        'success': True,
        'logs': [{
            'id': entry.id, 'change_type': entry.change_type, 'change_quantity': entry.change_quantity,
            'change_date': entry.change_date.strftime('%Y-%m-%d %H:%M:%S') if entry.change_date else '',
            'customer': entry.customer or '', 'related_id': entry.related_id or '', 'note': entry.note or '',
        } for entry in logs],
        'pagination': {
            'page': page, 'pages': calc_total_pages(total, per_page),
            'total': total,
        },
    }

async def get_case_products(db: AsyncSession, page: int = 1, per_page: int = 50, search: str = '') -> dict:
    """获取皮套产品列表（分页）。

    支持按 Case.name、Case.barcode、Product.name、Product.barcode 搜索。

    Args:
        db: 异步数据库会话。
        page: 页码，从 1 开始。
        per_page: 每页数量，1-200。
        search: 搜索关键词，空字符串表示不限制。

    Returns:
        dict，包含 cases（产品列表）、total（总数）、page、per_page。
    """
    page, per_page = _normalize_pagination(page, per_page, MAX_SUMMARY_PAGE_SIZE)
    query = select(Case).options(joinedload(Case.product))
    count_base = select(func.count()).select_from(Case)
    if search:
        pattern = f'%{escape_like(search)}%'
        query = query.outerjoin(Product, Case.product_id == Product.id).where(
            Case.name.like(pattern) | Case.barcode.like(pattern)
            | Product.name.like(pattern) | Product.barcode.like(pattern)
        )
        count_base = count_base.outerjoin(Product, Case.product_id == Product.id).where(
            Case.name.like(pattern) | Case.barcode.like(pattern)
            | Product.name.like(pattern) | Product.barcode.like(pattern)
        )
    total = (await db.execute(count_base)).scalar() or 0
    offset = (page - 1) * per_page
    result = await db.execute(query.order_by(Case.create_time.desc()).offset(offset).limit(per_page))
    cases = list(result.unique().scalars().all())
    return {
        'cases': [{
            'id': c.id, 'name': c.sync_name, 'barcode': c.sync_barcode or '',
            'image': c.image or '', 'current_stock': c.current_stock,
            'create_time': c.create_time.strftime('%Y-%m-%d') if c.create_time else '',
        } for c in cases],
        'total': total,
        'page': page,
        'per_page': per_page,
    }

async def get_case_stockin_detail(db: AsyncSession, stockin_id: int) -> dict:
    """获取单个皮套入库记录。

    Args:
        db: 异步数据库会话。
        stockin_id: 入库记录 ID。

    Returns:
        dict，包含入库记录字段。

    Raises:
        HTTPException: 入库记录不存在时抛出 404。
    """
    result = await db.execute(
        select(CaseStockIn).options(joinedload(CaseStockIn.case)).where(CaseStockIn.id == stockin_id)
    )
    stockin = result.unique().scalar_one_or_none()
    if not stockin:
        raise NotFoundError('入库记录不存在')
    return {
        'id': stockin.id, 'stockin_no': stockin.stockin_no,
        'stockin_date': stockin.stockin_date.strftime('%Y-%m-%d') if stockin.stockin_date else '',
        'customer': stockin.customer, 'case_id': stockin.case_id,
        'case_name': stockin.case.sync_name if stockin.case else '',
        'quantity': stockin.quantity, 'note': stockin.note or '',
    }

async def get_case_stockout_detail(db: AsyncSession, stockout_id: int) -> dict:
    """获取单个皮套出库记录。

    Args:
        db: 异步数据库会话。
        stockout_id: 出库记录 ID。

    Returns:
        dict，包含出库记录字段。

    Raises:
        HTTPException: 出库记录不存在时抛出 404。
    """
    result = await db.execute(
        select(CaseStockOut).options(joinedload(CaseStockOut.case)).where(CaseStockOut.id == stockout_id)
    )
    stockout = result.unique().scalar_one_or_none()
    if not stockout:
        raise NotFoundError('出库记录不存在')
    return {
        'id': stockout.id, 'stockout_no': stockout.stockout_no,
        'stockout_date': stockout.stockout_date.strftime('%Y-%m-%d') if stockout.stockout_date else '',
        'customer': stockout.customer or '', 'case_id': stockout.case_id,
        'case_name': stockout.case.sync_name if stockout.case else '',
        'quantity': stockout.quantity, 'note': stockout.note or '',
    }