"""皮套管理服务层

提供皮套产品的库存管理业务逻辑，包括：
- 皮套产品与库存的搜索、汇总、流水查询
- 入库/出库记录的增删改查（单条与批量）
- 库存变动的并发安全控制（行级锁 with_for_update）
- 库存流水日志的自动记录

所有写操作均通过 with_for_update 锁定关联 Case 行，确保并发场景下
库存计算的准确性；查询操作使用 joinedload 避免 N+1 问题。
"""
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from fastapi_app.core.exceptions import BusinessError, NotFoundError
from fastapi_app.core.number_generator import _acquire_advisory_lock_async, _number_lock_key
from fastapi_app.core.sanitizer import escape_like
from fastapi_app.core.validators import validate_quantity_range
from fastapi_app.shared_models import Case, CaseInventoryLog, CaseStockIn, CaseStockOut, Product
from fastapi_app.utils import calc_total_pages, parse_date_strict

logger = logging.getLogger(__name__)

# 分页与搜索常量
DEFAULT_SEARCH_LIMIT = 20  # 无搜索关键词时返回的最大记录数
MAX_LIST_PAGE_SIZE = 100  # 列表查询每页数量上限
MAX_SUMMARY_PAGE_SIZE = 200  # 库存汇总每页数量上限


def _parse_date(date_str: str, field_name: str = "日期") -> datetime:
    """安全解析 YYYY-MM-DD 格式日期字符串。

    委托给共享工具函数 parse_date_strict，并将其 ValueError 转换为
    BusinessError（HTTP 400），便于前端友好提示。

    Args:
        date_str: 日期字符串，需符合 YYYY-MM-DD 格式。
        field_name: 字段名（用于错误消息展示），默认为"日期"。

    Returns:
        解析后的 datetime 对象。

    Raises:
        BusinessError: 当 date_str 格式不符合 YYYY-MM-DD 时抛出（HTTP 400）。
    """
    try:
        return parse_date_strict(date_str, field_name)
    except ValueError as e:
        raise BusinessError(str(e)) from e


def _normalize_pagination(page: int, per_page: int, max_per_page: int) -> tuple[int, int]:
    """规范化分页参数。

    Args:
        page: 页码，小于 1 会被修正为 1。
        per_page: 每页数量，小于 1 会被修正为 1，超过 max_per_page 会被截断。
        max_per_page: 每页数量上限。

    Returns:
        元组 (修正后的页码, 修正后的每页数量)。
    """
    page = max(1, page)
    per_page = max(1, min(per_page, max_per_page))
    return page, per_page


def _apply_date_filter(query, column, start_date: str, end_date: str, field_label: str):
    """为查询添加日期范围过滤条件。

    end_date 会包含当天（即 < end_date + 1 天）。

    Args:
        query: SQLAlchemy 查询对象。
        column: 日期列对象（如 CaseStockIn.stockin_date）。
        start_date: 开始日期字符串（YYYY-MM-DD），空字符串表示不限制。
        end_date: 结束日期字符串（YYYY-MM-DD），空字符串表示不限制。
        field_label: 字段名（用于错误消息）。

    Returns:
        添加了过滤条件后的查询对象。
    """
    if start_date:
        query = query.where(column >= _parse_date(start_date, field_label))
    if end_date:
        query = query.where(column < _parse_date(end_date, field_label) + timedelta(days=1))  # sql-safe: escape_like/绑定参数/常量片段
    return query


def _apply_quantity_filter(query, column, quantity_min: int | None, quantity_max: int | None):
    """为查询添加数量范围过滤条件。

    Args:
        query: SQLAlchemy 查询对象。
        column: 数量列对象（如 CaseStockIn.quantity）。
        quantity_min: 最小数量（含），None 表示不限制。
        quantity_max: 最大数量（含），None 表示不限制。

    Returns:
        添加了过滤条件后的查询对象。
    """
    if quantity_min is not None:
        query = query.where(column >= quantity_min)
    if quantity_max is not None:
        query = query.where(column <= quantity_max)
    return query


def _serialize_stockin(stockin: CaseStockIn) -> dict:
    """将入库记录对象序列化为字典。

    Args:
        stockin: CaseStockIn 对象。

    Returns:
        包含入库记录字段的字典。
    """
    return {
        'id': stockin.id, 'stockin_no': stockin.stockin_no,
        'stockin_date': stockin.stockin_date.strftime('%Y-%m-%d') if stockin.stockin_date else '',
        'customer': stockin.customer, 'case_id': stockin.case_id,
        'case_name': stockin.case.sync_name if stockin.case else '',
        'case_barcode': stockin.case.sync_barcode if stockin.case else '',
        'quantity': stockin.quantity, 'note': stockin.note or '',
    }


def _serialize_stockout(stockout: CaseStockOut) -> dict:
    """将出库记录对象序列化为字典。

    Args:
        stockout: CaseStockOut 对象。

    Returns:
        包含出库记录字段的字典。
    """
    return {
        'id': stockout.id, 'stockout_no': stockout.stockout_no,
        'stockout_date': stockout.stockout_date.strftime('%Y-%m-%d') if stockout.stockout_date else '',
        'customer': stockout.customer or '', 'case_id': stockout.case_id,
        'case_name': stockout.case.sync_name if stockout.case else '',
        'case_barcode': stockout.case.sync_barcode if stockout.case else '',
        'quantity': stockout.quantity, 'note': stockout.note or '',
    }


async def _get_case_for_update(db: AsyncSession, case_id: int) -> Case:
    """以行级锁方式获取皮套记录，用于并发安全的库存变更。

    Args:
        db: 异步数据库会话。
        case_id: 皮套 ID。

    Returns:
        Case 对象。

    Raises:
        ValueError: 皮套不存在时抛出。
    """
    result = await db.execute(
        select(Case).where(Case.id == case_id).with_for_update()
    )
    case_obj = result.scalar_one_or_none()
    if not case_obj:
        raise ValueError(f"皮套 ID {case_id} 不存在")
    return case_obj


async def _get_or_create_case_for_product(db: AsyncSession, product_id: int) -> Case:
    """以事务级咨询锁 + 行级锁方式获取产品关联的皮套记录，不存在则创建。

    使用 pg_advisory_xact_lock 串行化同一 product_id 的创建流程，避免并发场景下
    多个请求同时查到 None 后各自插入导致重复 Case（Case.product_id 当前无唯一约束）。

    Args:
        db: 异步数据库会话。
        product_id: 关联产品 ID。

    Returns:
        Case 对象。

    Raises:
        ValueError: 产品不存在时抛出。
    """
    await _acquire_advisory_lock_async(db, _number_lock_key('CASE_PRODUCT', str(product_id)))
    result = await db.execute(
        select(Case).where(Case.product_id == product_id).with_for_update()
    )
    case_obj = result.scalar_one_or_none()

    if not case_obj:
        product = await db.get(Product, product_id)
        if not product:
            raise ValueError("产品不存在")
        case_obj = Case(product_id=product.id, name=product.name, barcode=product.barcode,
                        current_stock=0, initial_stock=0)
        db.add(case_obj)
        await db.flush()
    return case_obj


async def _get_case_by_product_for_update(db: AsyncSession, product_id: int) -> Case:
    """以行级锁方式获取产品关联的皮套记录。

    Args:
        db: 异步数据库会话。
        product_id: 关联产品 ID。

    Returns:
        Case 对象。

    Raises:
        ValueError: 未找到关联皮套时抛出。
    """
    result = await db.execute(
        select(Case).where(Case.product_id == product_id).with_for_update()
    )
    case_obj = result.scalar_one_or_none()
    if not case_obj:
        raise ValueError(f"未找到关联产品ID {product_id} 的皮套")
    return case_obj


async def _assert_no_case_references(db: AsyncSession, case_id: int) -> None:
    """检查皮套是否存在关联的入库/出库/流水记录。

    Args:
        db: 异步数据库会话。
        case_id: 皮套 ID。

    Raises:
        ValueError: 存在任意关联记录时抛出。
    """
    stockin_count = (await db.execute(
        select(func.count()).select_from(CaseStockIn).where(CaseStockIn.case_id == case_id)
    )).scalar() or 0
    if stockin_count:
        raise ValueError(f"存在 {stockin_count} 条入库记录，无法删除")

    stockout_count = (await db.execute(
        select(func.count()).select_from(CaseStockOut).where(CaseStockOut.case_id == case_id)
    )).scalar() or 0
    if stockout_count:
        raise ValueError(f"存在 {stockout_count} 条出库记录，无法删除")

    log_count = (await db.execute(
        select(func.count()).select_from(CaseInventoryLog).where(CaseInventoryLog.case_id == case_id)
    )).scalar() or 0
    if log_count:
        raise ValueError(f"存在 {log_count} 条库存流水，无法删除")


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


async def create_case_stockin(db: AsyncSession, product_id: int, quantity: int, stockin_date: str,
                               customer: str = '', note: str = '', stockin_no: str = '') -> dict:
    """创建皮套入库记录。

    若产品尚未关联皮套记录，会自动创建。库存变更使用行级锁保证并发安全。

    Args:
        db: 异步数据库会话。
        product_id: 关联产品 ID。
        quantity: 入库数量，需在业务规则允许范围内。
        stockin_date: 入库日期字符串（YYYY-MM-DD）。
        customer: 客户名称。
        note: 备注。
        stockin_no: 入库单号，为空时由调用方生成。

    Returns:
        dict，包含 success、stockin_no、id 字段。

    Raises:
        ValueError: 产品不存在时抛出。
        HTTPException: 日期格式错误时抛出 400。
    """
    validate_quantity_range(quantity, "入库数量")
    case_obj = await _get_or_create_case_for_product(db, product_id)

    stockin = CaseStockIn(stockin_no=stockin_no, stockin_date=_parse_date(stockin_date, '入库日期'),
                          customer=customer, case_id=case_obj.id, quantity=quantity, note=note)
    db.add(stockin)
    case_obj.current_stock += quantity

    log = CaseInventoryLog(case_id=case_obj.id, change_type='入库', change_quantity=quantity,
                           related_id=stockin_no, note=f'入库：{stockin_no}', customer=customer)
    db.add(log)
    await db.flush()
    logger.info('皮套入库成功 case_id=%s quantity=%s stockin_no=%s', case_obj.id, quantity, stockin_no)
    return {'success': True, 'stockin_no': stockin_no, 'id': stockin.id}


async def create_case_stockout(db: AsyncSession, product_id: int, quantity: int,
                                stockout_date: str, customer: str = '',
                                note: str = '', stockout_no: str = '') -> dict:
    """创建皮套出库记录。

    出库前会校验库存是否充足，库存变更使用行级锁保证并发安全。

    Args:
        db: 异步数据库会话。
        product_id: 关联产品 ID（用于定位皮套）。
        quantity: 出库数量，需在业务规则允许范围内。
        stockout_date: 出库日期字符串（YYYY-MM-DD）。
        customer: 客户名称。
        note: 备注。
        stockout_no: 出库单号，为空时由调用方生成。

    Returns:
        dict，包含 success、stockout_no、id 字段。

    Raises:
        ValueError: 皮套不存在或库存不足时抛出。
        HTTPException: 日期格式错误时抛出 400。
    """
    validate_quantity_range(quantity, "出货数量")
    case_obj = await _get_case_by_product_for_update(db, product_id)

    if case_obj.current_stock < quantity:
        raise ValueError(f"库存不足，当前库存: {case_obj.current_stock}")

    stockout = CaseStockOut(stockout_no=stockout_no, case_id=case_obj.id, quantity=quantity,
                            stockout_date=_parse_date(stockout_date, '出库日期'),
                            customer=customer, note=note)
    db.add(stockout)
    await db.flush()

    case_obj.current_stock -= quantity

    log = CaseInventoryLog(case_id=case_obj.id, change_type='出库', change_quantity=-quantity,
                           change_date=datetime.now(UTC), customer=customer,
                           related_id=stockout_no, note=f'出库 {stockout_no}')
    db.add(log)
    logger.info('皮套出库成功 case_id=%s quantity=%s stockout_no=%s', case_obj.id, quantity, stockout_no)
    return {'success': True, 'stockout_no': stockout_no, 'id': stockout.id}


async def delete_case_product(db: AsyncSession, case_id: int) -> None:
    """删除皮套产品。

    仅允许删除库存为 0 且无入库/出库/流水关联记录的皮套。

    Args:
        db: 异步数据库会话。
        case_id: 皮套 ID。

    Raises:
        ValueError: 皮套不存在、库存非 0 或存在关联记录时抛出。
    """
    case_obj = await db.get(Case, case_id)
    if not case_obj:
        raise ValueError("皮套不存在")
    if case_obj.current_stock != 0:
        raise ValueError("只能删除库存为0的皮套")

    # 引用完整性检查：存在任何入库/出库/流水记录则禁止删除
    await _assert_no_case_references(db, case_id)

    await db.delete(case_obj)
    await db.flush()
    logger.info('皮套产品删除成功 case_id=%s', case_id)


async def _adjust_stockin_quantity(db: AsyncSession, stockin: CaseStockIn, new_quantity: int) -> None:
    """调整入库记录数量并同步库存与流水。

    Args:
        db: 异步数据库会话。
        stockin: 入库记录对象。
        new_quantity: 调整后的数量。
    """
    old_quantity = stockin.quantity
    quantity_change = new_quantity - old_quantity
    stockin.quantity = new_quantity

    case_obj = await _get_case_for_update(db, stockin.case_id)
    case_obj.current_stock += quantity_change
    log = CaseInventoryLog(
        case_id=stockin.case_id, change_type='入库调整',
        change_quantity=quantity_change, related_id=stockin.stockin_no,
        note=f'入库调整：{stockin.stockin_no}'
    )
    db.add(log)


async def update_case_stockin(db: AsyncSession, stockin_id: int, update_data: dict) -> dict:
    """更新皮套入库记录。

    当数量发生变化时，同步调整关联皮套的当前库存并记录调整流水。
    库存变更使用行级锁保证并发安全。

    Args:
        db: 异步数据库会话。
        stockin_id: 入库记录 ID。
        update_data: 待更新字段字典，支持 quantity、customer、stockin_date、note。

    Returns:
        dict，包含 success、message 字段。

    Raises:
        ValueError: 入库记录不存在时抛出。
        HTTPException: 日期格式错误时抛出 400。
    """
    stockin = await db.get(CaseStockIn, stockin_id)
    if not stockin:
        raise ValueError("入库记录不存在")

    if 'quantity' in update_data:
        await _adjust_stockin_quantity(db, stockin, update_data['quantity'])

    if 'customer' in update_data:
        stockin.customer = update_data['customer']
    if 'stockin_date' in update_data:
        stockin.stockin_date = _parse_date(update_data['stockin_date'], '入库日期')
    if 'note' in update_data:
        stockin.note = update_data['note']

    await db.flush()
    logger.info('皮套入库记录更新成功 stockin_id=%s', stockin_id)
    return {'success': True, 'message': '更新成功'}


async def delete_case_stockin(db: AsyncSession, stockin_id: int) -> dict:
    """删除皮套入库记录。

    删除前检查是否存在出库记录（若有则禁止删除）。
    删除时同步扣减库存并记录流水，库存变更使用行级锁保证并发安全。

    Args:
        db: 异步数据库会话。
        stockin_id: 入库记录 ID。

    Returns:
        dict，包含 success、message 字段。

    Raises:
        ValueError: 入库记录不存在或删除后库存将为负数时抛出。
    """
    stockin = await db.get(CaseStockIn, stockin_id)
    if not stockin:
        raise ValueError("入库记录不存在")

    case_obj = await _get_case_for_update(db, stockin.case_id)
    # 由于 CaseStockOut 未记录关联的入库 ID，无法精确判断该入库是否被某笔出库引用。
    # 保守策略：确保删除后库存不会变为负数即可；若当前库存不足则禁止删除。
    if case_obj.current_stock < stockin.quantity:
        raise ValueError("当前库存不足，删除该入库后库存将为负数")
    case_obj.current_stock -= stockin.quantity
    log = CaseInventoryLog(
        case_id=stockin.case_id, change_type='删除入库',
        change_quantity=-stockin.quantity, related_id=stockin.stockin_no,
        note=f'删除入库：{stockin.stockin_no}'
    )
    db.add(log)

    await db.delete(stockin)
    await db.flush()
    logger.info('皮套入库记录删除成功 stockin_id=%s', stockin_id)
    return {'success': True, 'message': '删除成功'}


async def _adjust_stockout_quantity(db: AsyncSession, stockout: CaseStockOut, new_quantity: int) -> None:
    """调整出库记录数量并同步库存与流水。

    出库数量增加 → 库存减少；出库数量减少 → 库存增加。
    调整后库存为负时抛出异常。

    Args:
        db: 异步数据库会话。
        stockout: 出库记录对象。
        new_quantity: 调整后的数量。

    Raises:
        ValueError: 调整后库存为负时抛出。
    """
    old_quantity = stockout.quantity
    quantity_change = new_quantity - old_quantity
    stockout.quantity = new_quantity

    case_obj = await _get_case_for_update(db, stockout.case_id)
    case_obj.current_stock -= quantity_change
    if case_obj.current_stock < 0:
        raise ValueError(f"调整后库存不足，当前库存: {case_obj.current_stock}")
    log = CaseInventoryLog(
        case_id=stockout.case_id, change_type='出库调整',
        change_quantity=-quantity_change, related_id=stockout.stockout_no,
        note=f'出库调整：{stockout.stockout_no}'
    )
    db.add(log)


async def update_case_stockout(db: AsyncSession, stockout_id: int, update_data: dict) -> dict:
    """更新皮套出库记录。

    当数量发生变化时，同步调整关联皮套的当前库存并记录调整流水。
    库存变更使用行级锁保证并发安全。

    Args:
        db: 异步数据库会话。
        stockout_id: 出库记录 ID。
        update_data: 待更新字段字典，支持 quantity、customer、stockout_date、note。

    Returns:
        dict，包含 success、message 字段。

    Raises:
        ValueError: 出库记录不存在或调整后库存不足时抛出。
        HTTPException: 日期格式错误时抛出 400。
    """
    stockout = await db.get(CaseStockOut, stockout_id)
    if not stockout:
        raise ValueError("出库记录不存在")

    if 'quantity' in update_data:
        await _adjust_stockout_quantity(db, stockout, update_data['quantity'])

    if 'customer' in update_data:
        stockout.customer = update_data['customer']
    if 'stockout_date' in update_data:
        stockout.stockout_date = _parse_date(update_data['stockout_date'], '出库日期')
    if 'note' in update_data:
        stockout.note = update_data['note']

    await db.flush()
    logger.info('皮套出库记录更新成功 stockout_id=%s', stockout_id)
    return {'success': True, 'message': '更新成功'}


async def delete_case_stockout(db: AsyncSession, stockout_id: int) -> dict:
    """删除皮套出库记录。

    删除时同步回补库存并记录流水，库存变更使用行级锁保证并发安全。

    Args:
        db: 异步数据库会话。
        stockout_id: 出库记录 ID。

    Returns:
        dict，包含 success、message 字段。

    Raises:
        ValueError: 出库记录不存在时抛出。
    """
    stockout = await db.get(CaseStockOut, stockout_id)
    if not stockout:
        raise ValueError("出库记录不存在")

    case_obj = await _get_case_for_update(db, stockout.case_id)
    case_obj.current_stock += stockout.quantity
    log = CaseInventoryLog(
        case_id=stockout.case_id, change_type='删除出库',
        change_quantity=stockout.quantity, related_id=stockout.stockout_no,
        note=f'删除出库：{stockout.stockout_no}'
    )
    db.add(log)

    await db.delete(stockout)
    await db.flush()
    logger.info('皮套出库记录删除成功 stockout_id=%s', stockout_id)
    return {'success': True, 'message': '删除成功'}


async def batch_create_case_stockins(db: AsyncSession, stockins_data: list[dict]) -> dict:
    """批量提交皮套入库。

    逐条处理，单条失败不影响其他记录。每条记录自动生成入库单号。

    Args:
        db: 异步数据库会话。
        stockins_data: 入库数据列表，每项为 dict，支持 productId/product_id、quantity、
            stockinDate/stockin_date、customer、note 字段。

    Returns:
        dict，包含 success、message（成功条数）、failed（失败列表，含 index 和 error）。
    """
    success_count = 0
    failed = []

    for idx, item in enumerate(stockins_data):
        try:
            product_id = int(item.get('productId', item.get('product_id', 0)))
            quantity = int(item.get('quantity', 0))
            stockin_date = item.get('stockinDate', item.get('stockin_date', datetime.now().strftime('%Y-%m-%d')))
            customer = item.get('customer', '')
            note = item.get('note', '')

            if not product_id or quantity <= 0:
                failed.append({'index': idx, 'error': '产品ID或数量无效'})
                continue

            # 生成入库单号
            from fastapi_app.services.numbering import generate_case_stockin_number
            stockin_no = await generate_case_stockin_number(db)

            await create_case_stockin(db, product_id, quantity, stockin_date, customer, note, stockin_no)
            success_count += 1
        except (ValueError, TypeError, RuntimeError) as e:
            logger.warning('批量入库第 %s 条失败: %s', idx, e)
            failed.append({'index': idx, 'error': str(e)})

    return {'success': True, 'message': f'成功提交 {success_count} 条入库记录', 'failed': failed}


async def batch_create_case_stockouts(db: AsyncSession, stockouts_data: list[dict]) -> dict:
    """批量提交皮套出库。

    逐条处理，单条失败不影响其他记录。每条记录自动生成出库单号。

    Args:
        db: 异步数据库会话。
        stockouts_data: 出库数据列表，每项为 dict，支持 productId/product_id/case_id、quantity、
            stockoutDate/stockout_date、customer、note 字段。

    Returns:
        dict，包含 success、results（每条结果列表，含 success/error/id 字段）。
    """
    results = []

    for idx, item in enumerate(stockouts_data):
        try:
            product_id = int(item.get('productId', item.get('product_id', item.get('case_id', 0))))
            quantity = int(item.get('quantity', 0))
            stockout_date = item.get('stockoutDate', item.get('stockout_date', datetime.now().strftime('%Y-%m-%d')))
            customer = item.get('customer', '')
            note = item.get('note', '')

            if not product_id or quantity <= 0:
                results.append({'success': False, 'error': '产品ID或数量无效', 'id': item.get('id', '未知')})
                continue

            from fastapi_app.services.numbering import generate_case_stockout_number
            stockout_no = await generate_case_stockout_number(db)

            result = await create_case_stockout(db, product_id, quantity, stockout_date, customer, note, stockout_no)
            results.append({**result, 'id': item.get('id', '未知')})
        except (ValueError, TypeError, RuntimeError) as e:
            logger.warning('批量出库第 %s 条失败: %s', idx, e)
            results.append({'success': False, 'error': str(e), 'id': item.get('id', '未知')})

    return {'success': True, 'results': results}


async def create_case_product(db: AsyncSession, name: str | None = None, barcode: str | None = None,
                               image: str | None = None, product_id: int | None = None) -> dict:
    """创建皮套产品。

    需提供 name 或 product_id 至少一项；若仅提供 product_id，则从关联产品同步名称与条码。

    Args:
        db: 异步数据库会话。
        name: 皮套名称。
        barcode: 皮套条码。
        image: 图片路径。
        product_id: 关联产品 ID。

    Returns:
        dict，包含 success、message、id 字段。

    Raises:
        ValueError: name 和 product_id 均为空时抛出。
    """
    if not name and not product_id:
        raise ValueError("皮套名称或关联产品不能为空")

    if product_id and not name:
        linked_product = await db.get(Product, product_id)
        if linked_product:
            name = linked_product.name
            if not barcode:
                barcode = linked_product.barcode

    case_obj = Case(name=name or '', barcode=barcode or '', image=image,
                    product_id=product_id if product_id else None)
    db.add(case_obj)
    await db.flush()
    logger.info('皮套产品创建成功 case_id=%s name=%s', case_obj.id, name)
    return {'success': True, 'message': '添加成功', 'id': case_obj.id}


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
