"""报表统计服务层

SECURITY NOTE: where_clauses 列表仅包含硬编码的 SQL 片段，
禁止将用户输入直接拼接到 where_clauses 中，所有用户输入
必须通过 :param 参数绑定传递，以防止 SQL 注入。
"""
import logging
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.cache import cache_result
from fastapi_app.core.sanitizer import escape_like
from fastapi_app.utils import calc_total_pages, parse_date_strict

logger = logging.getLogger(__name__)


def _quote_identifier(name: str) -> str:
    """引用 SQL 标识符（PostgreSQL 双引号）

    系统仅支持 PostgreSQL，不再做方言分支。

    SECURITY: name 参数仅允许硬编码的表名/列名，禁止传入用户输入。
    """
    _ALLOWED_IDENTIFIERS = frozenset({
        'order', 'product', 'stock_in', 'stock_out', 'inventory_log',
        'customer', 'o', 's', 'p', 'so', 'si',
    })
    if name not in _ALLOWED_IDENTIFIERS:
        raise ValueError(f"非法SQL标识符: {name!r}，仅允许预定义标识符")  # sql-safe: escape_like/绑定参数/常量片段
    return f'"{name}"'


def _string_agg(expr: str, separator: str, distinct: bool = True) -> str:
    """返回字符串聚合表达式（PostgreSQL STRING_AGG）

    系统仅支持 PostgreSQL，不再保留 MySQL GROUP_CONCAT 分支。

    SECURITY: expr 参数仅允许硬编码的列引用，禁止传入用户输入。
    """
    _ALLOWED_EXPRS = frozenset({
        'o.order_no', 'o.note', 's.stockin_no', 's.note',
        'so.stockout_no', 'so.note', 'so.customer',
    })
    if expr not in _ALLOWED_EXPRS:
        raise ValueError(f"非法SQL聚合表达式: {expr!r}，仅允许预定义表达式")  # sql-safe: escape_like/绑定参数/常量片段
    if separator not in (', ', '; '):
        raise ValueError(f"非法SQL聚合分隔符: {separator!r}")  # sql-safe: escape_like/绑定参数/常量片段
    distinct_kw = "DISTINCT " if distinct else ""
    return f"STRING_AGG({distinct_kw}{expr}, '{separator}')"


async def _query_logs_generic(
    db: AsyncSession,
    *,
    base_where: list[str],
    data_sql_template: str,
    qty_sql_template: str,
    params: dict,
    page: int,
    per_page: int,
    row_mapper: callable,
) -> dict:
    """通用日志查询（分页+分组聚合+COUNT(*) OVER()合并计数）"""
    where_sql = (" AND " + " AND ".join(base_where)) if base_where else ""  # sql-safe: escape_like/绑定参数/常量片段
    params['limit'] = per_page
    params['offset'] = (page - 1) * per_page

    data_sql = data_sql_template.format(where_sql=where_sql)
    results = (await db.execute(text(data_sql), params)).fetchall()

    total = results[0].total_count if results else 0
    logs = [row_mapper(row) for row in results]

    qty_sql = qty_sql_template.format(where_sql=where_sql)
    total_qty = (await db.execute(text(qty_sql), params)).scalar() or 0

    return {
        'success': True,
        'logs': logs,
        'stats': {'total_count': total, 'total_quantity': total_qty},
        'pagination': {'page': page, 'per_page': per_page, 'total': total,
                       'pages': calc_total_pages(total, per_page)},
    }


@cache_result(
    key_prefix='reports:order_logs',
    ttl=30,
    local_ttl=10,
    key_builder=lambda *args, **kwargs: f"c:{kwargs.get('customer','')}:p:{kwargs.get('product','')}:s:{kwargs.get('status','')}:sd:{kwargs.get('start_date','')}:ed:{kwargs.get('end_date','')}:pg:{kwargs.get('page',1)}:pp:{kwargs.get('per_page',20)}",
)
async def get_order_logs(db: AsyncSession, customer: str = '', product: str = '', status: str = '',
                         start_date: str = '', end_date: str = '',
                         page: int = 1, per_page: int = 20) -> dict:
    """订单流水（分页+分组聚合，COUNT(*) OVER() 合并计数查询）"""
    per_page = min(max(1, per_page), 100)
    customer = customer.strip()[:100]
    product = product.strip()[:100]

    where_clauses = ["(o.is_deleted = false OR o.is_deleted IS NULL)"]
    params = {}

    if customer:
        where_clauses.append("o.customer LIKE :customer")
        params['customer'] = f'%{escape_like(customer)}%'
    if product:
        where_clauses.append("(p.name LIKE :product OR p.barcode LIKE :product)")
        params['product'] = f'%{escape_like(product)}%'
    if status:
        valid = ['待备货', '部分备货', '已备货', '待出货', '已出货', '已取消']
        if status in valid:
            where_clauses.append("o.status = :status")
            params['status'] = status
    if start_date:
        params['start_date'] = parse_date_strict(start_date, '开始')
        where_clauses.append("o.order_date >= :start_date")
    if end_date:
        params['end_date'] = parse_date_strict(end_date, '结束') + timedelta(days=1)
        where_clauses.append("o.order_date < :end_date")

    order_tbl = _quote_identifier("order")

    return await _query_logs_generic(
        db,
        base_where=where_clauses,
        params=params,
        page=page,
        per_page=per_page,
        data_sql_template=f"""SELECT
        DATE(o.order_date) as order_date_only, o.customer, p.name as product_name,
        p.barcode as product_barcode, o.status,
        SUM(o.quantity) as total_quantity, COUNT(o.id) as order_count,
        {_string_agg('o.order_no', ', ')} as order_nos,
        {_string_agg('o.note', '; ')} as notes,
        COUNT(*) OVER() as total_count
        FROM {order_tbl} o JOIN product p ON o.product_id = p.id
        WHERE 1=1 {{where_sql}}
        GROUP BY DATE(o.order_date), o.customer, p.name, p.barcode, o.status
        ORDER BY DATE(o.order_date) DESC
        LIMIT :limit OFFSET :offset""",  # nosec B608
        qty_sql_template=f"SELECT COALESCE(SUM(o.quantity), 0) FROM {order_tbl} o JOIN product p ON o.product_id = p.id WHERE 1=1 {{where_sql}}",  # nosec B608
        row_mapper=lambda row: {
            'order_date': row.order_date_only.strftime('%Y-%m-%d') if row.order_date_only else '-',
            'customer': row.customer, 'product_name': row.product_name,
            'product_barcode': row.product_barcode or '',
            'quantity': row.total_quantity, 'status': row.status,
            'order_count': row.order_count,
            'order_nos': row.order_nos or '', 'note': row.notes or '',
        },
    )


async def export_report_to_excel(db, report_type: str, customer: str = '', product: str = '',
                                  status: str = '', start_date: str = '', end_date: str = '') -> bytes:
    """导出报表为 Excel（内存缓冲区）

    使用框架无关的 report_data_service 查询数据，通过 ReportExporter 生成 Excel，
    在同步线程中执行以避免阻塞事件循环。
    """
    import asyncio

    from fastapi_app.core.database import SyncSessionLocal
    from fastapi_app.shared.report_data_service import get_all_logs_data
    from utils.report_exporter import ReportExporter

    if SyncSessionLocal is None:
        raise RuntimeError('SyncSessionLocal 未配置，无法导出报表。请检查数据库配置。')

    def _sync_export():
        session = SyncSessionLocal()
        try:
            logs, stats = get_all_logs_data(
                session, report_type,
                customer=customer, product=product, status=status,
                start_date=start_date, end_date=end_date
            )

            truncated = len(logs) > 10000
            if truncated:
                logger.warning(f"报表导出截断：共{len(logs)}条，仅导出前10000条")
                logs = logs[:10000]

            exporter = ReportExporter()
            export_methods = {
                "order": exporter.export_order_logs,
                "stockin": exporter.export_stockin_logs,
                "stockout": exporter.export_stockout_logs,
                "deduction": exporter.export_deduction_logs,
            }

            export_func = export_methods.get(report_type)
            if not export_func:
                raise ValueError(f"不支持的报表类型: {report_type}")

            output = export_func(logs, stats)
            if isinstance(output, bytes):
                return output
            return output.getvalue()
        finally:
            session.close()

    # 在线程池中执行同步操作
    loop = asyncio.get_running_loop()
    content = await loop.run_in_executor(None, _sync_export)
    return content


@cache_result(
    key_prefix='reports:stockin_logs',
    ttl=30,
    local_ttl=10,
    key_builder=lambda *args, **kwargs: f"c:{kwargs.get('customer','')}:p:{kwargs.get('product','')}:sd:{kwargs.get('start_date','')}:ed:{kwargs.get('end_date','')}:pg:{kwargs.get('page',1)}:pp:{kwargs.get('per_page',20)}",
)
async def get_stockin_logs(db: AsyncSession, customer: str = '', product: str = '',
                           start_date: str = '', end_date: str = '',
                           page: int = 1, per_page: int = 20) -> dict:
    """备货流水（分页+分组聚合，COUNT(*) OVER() 合并计数查询）"""
    per_page = min(max(1, per_page), 100)
    customer = customer.strip()[:100]
    product = product.strip()[:100]

    where_clauses = []
    params = {}

    if customer:
        where_clauses.append("COALESCE(s.customer, '') LIKE :customer")
        params['customer'] = f'%{escape_like(customer)}%'
    if product:
        where_clauses.append("(COALESCE(p.name, '') LIKE :product OR COALESCE(p.barcode, '') LIKE :product)")
        params['product'] = f'%{escape_like(product)}%'
    if start_date:
        params['start_date'] = parse_date_strict(start_date, '开始')
        where_clauses.append("s.stockin_date >= :start_date")
    if end_date:
        params['end_date'] = parse_date_strict(end_date, '结束') + timedelta(days=1)
        where_clauses.append("s.stockin_date < :end_date")

    return await _query_logs_generic(
        db,
        base_where=where_clauses,
        params=params,
        page=page,
        per_page=per_page,
        data_sql_template=f"""SELECT
        DATE(s.stockin_date) as stockin_date_only, s.customer, p.name as product_name,
        p.barcode as product_barcode,
        SUM(s.quantity) as total_quantity, COUNT(s.id) as stockin_count,
        {_string_agg('s.stockin_no', ', ')} as stockin_nos,
        {_string_agg('s.note', '; ')} as notes,
        COUNT(*) OVER() as total_count
        FROM stock_in s JOIN product p ON s.product_id = p.id
        WHERE 1=1 {{where_sql}}
        GROUP BY DATE(s.stockin_date), s.customer, p.name, p.barcode
        ORDER BY DATE(s.stockin_date) DESC
        LIMIT :limit OFFSET :offset""",  # nosec B608
        qty_sql_template="SELECT COALESCE(SUM(s.quantity), 0) FROM stock_in s JOIN product p ON s.product_id = p.id WHERE 1=1 {where_sql}",
        row_mapper=lambda row: {
            'stockin_date': row.stockin_date_only.strftime('%Y-%m-%d') if row.stockin_date_only else '-',
            'customer': row.customer, 'product_name': row.product_name,
            'product_barcode': row.product_barcode or '',
            'quantity': row.total_quantity, 'stockin_count': row.stockin_count,
            'stockin_nos': row.stockin_nos or '', 'note': row.notes or '',
        },
    )


@cache_result(
    key_prefix='reports:stockout_logs',
    ttl=30,
    local_ttl=10,
    key_builder=lambda *args, **kwargs: f"c:{kwargs.get('customer','')}:p:{kwargs.get('product','')}:sd:{kwargs.get('start_date','')}:ed:{kwargs.get('end_date','')}:pg:{kwargs.get('page',1)}:pp:{kwargs.get('per_page',20)}",
)
async def get_stockout_logs(db: AsyncSession, customer: str = '', product: str = '',
                            start_date: str = '', end_date: str = '',
                            page: int = 1, per_page: int = 20) -> dict:
    """出货流水（仅手动出货，stockin_id IS NULL，COUNT(*) OVER() 合并计数查询）"""
    per_page = min(max(1, per_page), 100)
    customer = customer.strip()[:100]
    product = product.strip()[:100]

    where_clauses = ["(so.quantity - so.returned_quantity) > 0", "so.stockin_id IS NULL",
                     "(so.order_id IS NULL OR o2.is_deleted = false OR o2.is_deleted IS NULL)"]
    params = {}

    if customer:
        where_clauses.append("COALESCE(so.customer, '') LIKE :customer")
        params['customer'] = f'%{escape_like(customer)}%'
    if product:
        where_clauses.append("(COALESCE(p.name, '') LIKE :product OR COALESCE(p.barcode, '') LIKE :product)")
        params['product'] = f'%{escape_like(product)}%'
    if start_date:
        params['start_date'] = parse_date_strict(start_date, '开始')
        where_clauses.append("so.stockout_date >= :start_date")
    if end_date:
        params['end_date'] = parse_date_strict(end_date, '结束') + timedelta(days=1)
        where_clauses.append("so.stockout_date < :end_date")

    return await _query_logs_generic(
        db,
        base_where=where_clauses,
        params=params,
        page=page,
        per_page=per_page,
        data_sql_template=f"""SELECT
        DATE(so.stockout_date) as stockout_date_only, so.customer, p.name as product_name,
        p.barcode as product_barcode,
        SUM(so.quantity - so.returned_quantity) as total_quantity, COUNT(so.id) as stockout_count,
        {_string_agg('so.stockout_no', ', ')} as stockout_nos,
        {_string_agg('so.note', '; ')} as notes,
        COUNT(*) OVER() as total_count
        FROM stock_out so JOIN product p ON so.product_id = p.id
        LEFT JOIN "order" o2 ON so.order_id = o2.id
        WHERE 1=1 {{where_sql}}
        GROUP BY DATE(so.stockout_date), so.customer, p.name, p.barcode
        ORDER BY DATE(so.stockout_date) DESC
        LIMIT :limit OFFSET :offset""",  # nosec B608
        qty_sql_template="""SELECT COALESCE(SUM(so.quantity - so.returned_quantity), 0)
        FROM stock_out so JOIN product p ON so.product_id = p.id
        LEFT JOIN "order" o2 ON so.order_id = o2.id
        WHERE 1=1 {where_sql}""",
        row_mapper=lambda row: {
            'stockout_date': row.stockout_date_only.strftime('%Y-%m-%d') if row.stockout_date_only else '-',
            'customer': row.customer or '', 'product_name': row.product_name,
            'product_barcode': row.product_barcode or '',
            'quantity': row.total_quantity, 'stockout_count': row.stockout_count,
            'stockout_nos': row.stockout_nos or '', 'note': row.notes or '',
        },
    )


@cache_result(
    key_prefix='reports:deduction_logs',
    ttl=30,
    local_ttl=10,
    key_builder=lambda *args, **kwargs: f"c:{kwargs.get('customer','')}:p:{kwargs.get('product','')}:sd:{kwargs.get('start_date','')}:ed:{kwargs.get('end_date','')}:pg:{kwargs.get('page',1)}:pp:{kwargs.get('per_page',20)}",
)
async def get_deduction_logs(db: AsyncSession, customer: str = '', product: str = '',
                              start_date: str = '', end_date: str = '',
                              page: int = 1, per_page: int = 20) -> dict:
    """备货抵扣流水（stockin_id IS NOT NULL，COUNT(*) OVER() 合并计数查询）"""
    per_page = min(max(1, per_page), 100)
    customer = customer.strip()[:100]
    product = product.strip()[:100]

    where_clauses = ["so.stockin_id IS NOT NULL",
                     "(o.is_deleted = false OR o.is_deleted IS NULL)"]
    params = {}

    if customer:
        where_clauses.append("COALESCE(so.customer, '') LIKE :customer")
        params['customer'] = f'%{escape_like(customer)}%'
    if product:
        where_clauses.append("(COALESCE(p.name, '') LIKE :product OR COALESCE(p.barcode, '') LIKE :product)")
        params['product'] = f'%{escape_like(product)}%'
    if start_date:
        params['start_date'] = parse_date_strict(start_date, '开始')
        where_clauses.append("so.stockout_date >= :start_date")
    if end_date:
        params['end_date'] = parse_date_strict(end_date, '结束') + timedelta(days=1)
        where_clauses.append("so.stockout_date < :end_date")

    order_tbl = _quote_identifier('order')

    return await _query_logs_generic(
        db,
        base_where=where_clauses,
        params=params,
        page=page,
        per_page=per_page,
        data_sql_template=f"""SELECT
        DATE(so.stockout_date) as deduction_date_only, so.customer, p.name as product_name,
        p.barcode as sku,
        SUM(so.quantity - so.returned_quantity) as total_quantity, COUNT(so.id) as deduction_count,
        {_string_agg('o.order_no', ', ')} as order_nos,
        {_string_agg('o.note', '; ')} as order_notes,
        COUNT(*) OVER() as total_count
        FROM stock_out so JOIN product p ON so.product_id = p.id
        LEFT JOIN {order_tbl} o ON so.order_id = o.id
        WHERE 1=1 {{where_sql}}
        GROUP BY DATE(so.stockout_date), so.customer, p.name, p.barcode
        ORDER BY DATE(so.stockout_date) DESC
        LIMIT :limit OFFSET :offset""",  # nosec B608
        qty_sql_template=f"""SELECT COALESCE(SUM(so.quantity - so.returned_quantity), 0)
        FROM stock_out so JOIN product p ON so.product_id = p.id
        LEFT JOIN {order_tbl} o ON so.order_id = o.id
        WHERE 1=1 {{where_sql}}""",  # nosec B608
        row_mapper=lambda row: {
            'deduction_time': row.deduction_date_only.strftime('%Y-%m-%d') if row.deduction_date_only else '-',
            'customer': row.customer or '', 'product_name': row.product_name,
            'sku': row.sku or '',
            'quantity': row.total_quantity, 'deduction_count': row.deduction_count,
            'order_nos': row.order_nos or '', 'order_note': row.order_notes or '',
        },
    )
