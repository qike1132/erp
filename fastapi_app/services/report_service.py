"""报表统计服务层

SECURITY NOTE: where_clauses 列表仅包含硬编码的 SQL 片段，
禁止将用户输入直接拼接到 where_clauses 中，所有用户输入
必须通过 :param 参数绑定传递，以防止 SQL 注入。
"""
import logging
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.cache import cache_result
from fastapi_app.core.sanitizer import escape_like
from fastapi_app.shared_models.order import VALID_ORDER_STATUSES
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
        'sr.return_no', 'sr.reason', 'sr.note',
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
    # 注解原为内置函数 `callable`（不是类型！），mypy 报 `callable? not callable`。
    # 调用方一律传 `lambda row: {...}`，故用 Callable[[Any], dict]。
    row_mapper: Callable[[Any], dict],
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


def _order_logs_sql(order_tbl: str, item_join: str, item_qty: str,
                    item_name: str, item_barcode: str,
                    item_where_sql: str) -> tuple[str, str]:
    """订单流水的 (data_sql, qty_sql) 模板（2026-10-13 改母行-明细）。

    按**订单**分页（LIMIT/OFFSET 落在订单上）、展开为一行一个 (订单 × SKU)。
    data_sql 必须自带 `total_count` 列（`_query_logs_generic` 取 `results[0].total_count`）：
    CTE 已 `GROUP BY o.id`（每行=一张订单），`COUNT(*) OVER ()` 在 LIMIT **之前**求值
    → 全量匹配的**订单数**（不能用展开后的 `COUNT(*)`，那是 SKU 行数）。
    qty_sql 保持「Σ 明细数量」语义（进 stats.total_quantity），不挪用成订单数。

    `item_where_sql`：**明细级**筛选（产品/工厂），只作用于外层展开行 —— 保留旧契约
    「按某 SKU 筛选时只出该 SKU 行，而非整单全部 SKU」（CTE 里用全量 where 选订单，
    外层用它收窄到匹配的明细行）。
    """
    data_sql = f"""WITH page_orders AS (
        SELECT o.id, COUNT(*) OVER () AS total_count
        FROM {order_tbl} o
        LEFT JOIN order_item oi ON oi.order_id = o.id
        LEFT JOIN product p ON p.id = COALESCE(oi.product_id, o.product_id)
        WHERE 1=1 {{where_sql}}
        GROUP BY o.id
        ORDER BY MAX(o.order_date) DESC, o.id DESC
        LIMIT :limit OFFSET :offset
    )
    SELECT o.id AS order_id, o.order_no,
           to_char(o.order_date, 'YYYY-MM-DD HH24:MI') AS order_date,
           o.customer, o.note AS order_note,
           oi.id AS item_id, {item_name} AS product_name,
           {item_barcode} AS product_barcode,
           {item_qty} AS quantity, oi.note AS item_note,
           COUNT(*) OVER (PARTITION BY o.id) AS item_count,
           SUM({item_qty}) OVER (PARTITION BY o.id) AS order_total_qty,
           po.total_count
    FROM page_orders po
    JOIN {order_tbl} o ON o.id = po.id
    LEFT JOIN order_item oi ON oi.order_id = o.id
    LEFT JOIN product p ON p.id = COALESCE(oi.product_id, o.product_id)
    WHERE 1=1 {item_where_sql}
    ORDER BY o.order_date DESC, o.id DESC, oi.id"""  # nosec B608
    qty_sql = (
        f"SELECT COALESCE(SUM({item_qty}), 0) FROM {order_tbl} o {item_join} "
        "WHERE 1=1 {where_sql}"
    )  # nosec B608
    return data_sql, qty_sql


@cache_result(
    key_prefix='reports:order_logs',
    ttl=30,
    local_ttl=10,
    key_builder=lambda *args, **kwargs: f"c:{kwargs.get('customer','')}:p:{kwargs.get('product','')}:s:{kwargs.get('status','')}:f:{kwargs.get('factory','')}:sd:{kwargs.get('start_date','')}:ed:{kwargs.get('end_date','')}:pg:{kwargs.get('page',1)}:pp:{kwargs.get('per_page',20)}",
)
async def get_order_logs(db: AsyncSession, customer: str = '', product: str = '', status: str = '',
                         start_date: str = '', end_date: str = '',
                         page: int = 1, per_page: int = 20, factory: str = '') -> dict:
    """订单流水（按订单分页、一行一 SKU；母行-明细由前端按 order_id 聚合）。

    2026-10-13 改造：由「按 (日期,客户,产品) 分组」改为「按订单分页 + 展开 SKU」，
    每行带订单级字段（order_id/order_no/order_date 到分/order_note/item_count/
    order_total_qty）与 SKU 级字段（item_id/product_name/product_barcode/quantity/item_note）。
    """
    per_page = min(max(1, per_page), 100)
    customer = customer.strip()[:100]
    product = product.strip()[:100]

    where_clauses = ["(o.is_deleted = false OR o.is_deleted IS NULL)"]
    # 明细级筛选（产品/工厂）：CTE 用全量 where 选订单，外层用它收窄到匹配的 SKU 行
    item_where_clauses: list[str] = []
    params: dict[str, object] = {}

    if customer:
        where_clauses.append("o.customer LIKE :customer")
        params['customer'] = f'%{escape_like(customer)}%'
    if product:
        # 与 SELECT 的显示口径同源（item_name/item_barcode 都是
        # COALESCE(p.*, oi.*)）：否则产品行缺失（被删）的 SKU 行会「显示得出、
        # 按名字搜不到」——左连接下 p.name 为 NULL，旧写法直接把它排除掉。
        # 2026-10-13：搜索框兼作「订单号」搜索——追加 o.order_no 匹配（订单级条件，
        # 命中即整单所有 SKU 行都出；前端搜索框占位符已同步为「产品名称 / SKU / 订单号」）。
        cond = ("(COALESCE(p.name, oi.product_name) LIKE :product "
                "OR COALESCE(p.barcode, oi.product_barcode) LIKE :product "
                "OR o.order_no LIKE :product)")
        where_clauses.append(cond)
        item_where_clauses.append(cond)
        params['product'] = f'%{escape_like(product)}%'
    if factory:
        where_clauses.append("p.factory = :factory")
        item_where_clauses.append("p.factory = :factory")
        params['factory'] = factory
    if status:
        valid = VALID_ORDER_STATUSES
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

    # 多 SKU 订单：Order.product_id/quantity 是「首个 SKU / 全部 SKU 之和」兼容值，
    # 故按 order_item 展开，一行 = 一个 (订单 × SKU)；无明细的历史订单回退兼容列
    # （LEFT JOIN + COALESCE，避免被内连接丢掉）。
    item_join = ("LEFT JOIN order_item oi ON oi.order_id = o.id "
                 "LEFT JOIN product p ON p.id = COALESCE(oi.product_id, o.product_id)")
    item_qty = "COALESCE(oi.quantity, o.quantity)"
    item_name = "COALESCE(p.name, oi.product_name)"
    item_barcode = "COALESCE(p.barcode, oi.product_barcode)"

    item_where_sql = (" AND " + " AND ".join(item_where_clauses)) if item_where_clauses else ""
    data_sql, qty_sql = _order_logs_sql(
        order_tbl, item_join, item_qty, item_name, item_barcode, item_where_sql)

    return await _query_logs_generic(
        db,
        base_where=where_clauses,
        params=params,
        page=page,
        per_page=per_page,
        data_sql_template=data_sql,
        qty_sql_template=qty_sql,
        row_mapper=lambda row: {
            'order_id': row.order_id,
            'item_id': row.item_id or 0,          # 无明细历史订单 LEFT JOIN 出 NULL
            'order_no': row.order_no or '',
            'order_date': row.order_date or '-',  # 已是 to_char 文本（到分）
            'customer': row.customer or '',
            'product_name': row.product_name or '',
            'product_barcode': row.product_barcode or '',
            'quantity': row.quantity or 0,
            'item_note': row.item_note or '',
            'order_note': row.order_note or '',
            'note': row.item_note or row.order_note or '',
            'item_count': row.item_count or 1,
            'order_total_qty': int(row.order_total_qty or 0),
        },
    )


@cache_result(
    key_prefix='reports:return_logs',
    ttl=30,
    local_ttl=10,
    key_builder=lambda *args, **kwargs: f"c:{kwargs.get('customer','')}:p:{kwargs.get('product','')}:s:{kwargs.get('status','')}:f:{kwargs.get('factory','')}:sd:{kwargs.get('start_date','')}:ed:{kwargs.get('end_date','')}:pg:{kwargs.get('page',1)}:pp:{kwargs.get('per_page',20)}",
)
async def get_return_logs(db: AsyncSession, customer: str = '', product: str = '',
                          start_date: str = '', end_date: str = '',
                          page: int = 1, per_page: int = 20, factory: str = '') -> dict:
    """退货流水（仅 active，cancelled 已对称扣回不计入，COUNT(*) OVER() 合并计数查询）"""
    per_page = min(max(1, per_page), 100)
    customer = customer.strip()[:100]
    product = product.strip()[:100]

    where_clauses = ["sr.status = 'active'"]
    params: dict[str, object] = {}

    if customer:
        where_clauses.append("COALESCE(sr.customer, '') LIKE :customer")
        params['customer'] = f'%{escape_like(customer)}%'
    if product:
        where_clauses.append("(COALESCE(p.name, '') LIKE :product OR COALESCE(p.barcode, '') LIKE :product)")
        params['product'] = f'%{escape_like(product)}%'
    if factory:
        where_clauses.append("p.factory = :factory")
        params['factory'] = factory
    if start_date:
        params['start_date'] = parse_date_strict(start_date, '开始')
        where_clauses.append("sr.return_date >= :start_date")
    if end_date:
        params['end_date'] = parse_date_strict(end_date, '结束') + timedelta(days=1)
        where_clauses.append("sr.return_date < :end_date")

    return await _query_logs_generic(
        db,
        base_where=where_clauses,
        params=params,
        page=page,
        per_page=per_page,
        data_sql_template="""SELECT
        sr.id AS record_id, sr.return_no AS record_no,
        to_char(sr.return_date, 'YYYY-MM-DD HH24:MI') AS return_date,
        sr.customer, p.name AS product_name, p.barcode AS product_barcode,
        sr.quantity, sr.reason, sr.note,
        COUNT(*) OVER() AS total_count
        FROM stock_return sr JOIN product p ON sr.product_id = p.id
        WHERE 1=1 {where_sql}
        ORDER BY sr.return_date DESC, sr.id DESC
        LIMIT :limit OFFSET :offset""",  # nosec B608
        qty_sql_template="SELECT COALESCE(SUM(sr.quantity), 0) FROM stock_return sr JOIN product p ON sr.product_id = p.id WHERE 1=1 {where_sql}",
        row_mapper=lambda row: {
            'record_id': row.record_id, 'record_no': row.return_no or '',
            'return_date': row.return_date or '-', 'customer': row.customer or '',
            'product_name': row.product_name or '', 'product_barcode': row.product_barcode or '',
            'quantity': row.quantity or 0,
            # reason/note 分开下发：行内编辑要原值回写，note 若给合并串会把原因写进备注字段
            'reason': row.reason or '', 'note': row.note or '',
            'note_display': '；'.join(x for x in (row.reason or '', row.note or '') if x),
        },
    )


async def export_report_to_excel(db, report_type: str, customer: str = '', product: str = '',
                                  status: str = '', start_date: str = '', end_date: str = '',
                                  factory: str = '') -> bytes:
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
                start_date=start_date, end_date=end_date, factory=factory
            )

            # 超限判定用 stats 的 total_count（统计查询无行数上限）：明细查询在
            # _MAX_EXPORT_ROWS 截断，len(logs) 恒 ≤10000，原 `len(logs) > 10000`
            # 永不触发（Round16：截断标记是死代码，超量被静默截断且无告警）
            total_count = int(stats.get('total_count', 0) or 0)
            # P1（2026-10-24）：超限改为明确拒绝，不再静默截断。
            # 原实现只写 logger.warning 就把 logs 截到 10000，用户拿到少数据的 Excel
            # 且页面无任何提示，对账缺行无法察觉；同仓 export_limits 对超限是抛错
            # （端点转 4xx），两套口径并存。这里对齐 export_limits：拒绝并告知实际条数。
            if total_count > 10000:
                logger.warning(f"报表导出超限：共{total_count}条，上限10000条，已拒绝导出")
                raise ValueError(
                    f'导出数据量 {total_count} 条超过单次上限 10000 条，'
                    f'请缩小日期范围或增加筛选条件后重试'
                )

            exporter = ReportExporter()
            export_methods = {
                "order": exporter.export_order_logs,
                "stockin": exporter.export_stockin_logs,
                "stockout": exporter.export_stockout_logs,
                "deduction": exporter.export_deduction_logs,
                "return": exporter.export_return_logs,
            }

            export_func = export_methods.get(report_type)
            if not export_func:
                raise ValueError(f"不支持的报表类型: {report_type}")

            output = export_func(logs)
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
    key_builder=lambda *args, **kwargs: f"c:{kwargs.get('customer','')}:p:{kwargs.get('product','')}:s:{kwargs.get('status','')}:f:{kwargs.get('factory','')}:sd:{kwargs.get('start_date','')}:ed:{kwargs.get('end_date','')}:pg:{kwargs.get('page',1)}:pp:{kwargs.get('per_page',20)}",
)
async def get_stockin_logs(db: AsyncSession, customer: str = '', product: str = '',
                           start_date: str = '', end_date: str = '',
                           page: int = 1, per_page: int = 20, factory: str = '') -> dict:
    """备货流水（分页+分组聚合，COUNT(*) OVER() 合并计数查询）"""
    per_page = min(max(1, per_page), 100)
    customer = customer.strip()[:100]
    product = product.strip()[:100]

    where_clauses = []
    params: dict[str, object] = {}

    if customer:
        where_clauses.append("COALESCE(s.customer, '') LIKE :customer")
        params['customer'] = f'%{escape_like(customer)}%'
    if product:
        where_clauses.append("(COALESCE(p.name, '') LIKE :product OR COALESCE(p.barcode, '') LIKE :product)")
        params['product'] = f'%{escape_like(product)}%'
    if factory:
        where_clauses.append("p.factory = :factory")
        params['factory'] = factory
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
        data_sql_template="""SELECT
        s.id AS record_id, s.stockin_no AS record_no,
        to_char(s.stockin_date, 'YYYY-MM-DD HH24:MI') AS stockin_date,
        s.customer, p.name AS product_name, p.barcode AS product_barcode,
        s.quantity, s.note,
        COUNT(*) OVER() AS total_count
        FROM stock_in s JOIN product p ON s.product_id = p.id
        WHERE 1=1 {where_sql}
        ORDER BY s.stockin_date DESC, s.id DESC
        LIMIT :limit OFFSET :offset""",  # nosec B608
        qty_sql_template="SELECT COALESCE(SUM(s.quantity), 0) FROM stock_in s JOIN product p ON s.product_id = p.id WHERE 1=1 {where_sql}",
        row_mapper=lambda row: {
            'record_id': row.record_id, 'record_no': row.record_no or '',
            'stockin_date': row.stockin_date or '-', 'customer': row.customer or '',
            'product_name': row.product_name or '', 'product_barcode': row.product_barcode or '',
            'quantity': row.quantity or 0, 'note': row.note or '',
        },
    )


@cache_result(
    key_prefix='reports:stockout_logs',
    ttl=30,
    local_ttl=10,
    key_builder=lambda *args, **kwargs: f"c:{kwargs.get('customer','')}:p:{kwargs.get('product','')}:s:{kwargs.get('status','')}:f:{kwargs.get('factory','')}:sd:{kwargs.get('start_date','')}:ed:{kwargs.get('end_date','')}:pg:{kwargs.get('page',1)}:pp:{kwargs.get('per_page',20)}",
)
async def get_stockout_logs(db: AsyncSession, customer: str = '', product: str = '',
                            start_date: str = '', end_date: str = '',
                            page: int = 1, per_page: int = 20, factory: str = '') -> dict:
    """出货流水（仅手动出货，stockin_id IS NULL，COUNT(*) OVER() 合并计数查询）。

    数量为**出货毛量**（SUM(quantity)），不扣退货——退货在「退货流水」tab 单独呈现，
    故已全退的出货单仍按原出货量显示（2026-10-08 业务裁定）。
    """
    per_page = min(max(1, per_page), 100)
    customer = customer.strip()[:100]
    product = product.strip()[:100]

    where_clauses = ["so.quantity > 0", "so.stockin_id IS NULL",
                     "(so.order_id IS NULL OR o2.is_deleted = false OR o2.is_deleted IS NULL)"]
    params: dict[str, object] = {}

    if customer:
        where_clauses.append("COALESCE(so.customer, '') LIKE :customer")
        params['customer'] = f'%{escape_like(customer)}%'
    if product:
        where_clauses.append("(COALESCE(p.name, '') LIKE :product OR COALESCE(p.barcode, '') LIKE :product)")
        params['product'] = f'%{escape_like(product)}%'
    if factory:
        where_clauses.append("p.factory = :factory")
        params['factory'] = factory
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
        data_sql_template="""SELECT
        so.id AS record_id, so.stockout_no AS record_no,
        to_char(so.stockout_date, 'YYYY-MM-DD HH24:MI') AS stockout_date,
        so.customer, p.name AS product_name, p.barcode AS product_barcode,
        so.quantity, so.note,
        COUNT(*) OVER() AS total_count
        FROM stock_out so JOIN product p ON so.product_id = p.id
        LEFT JOIN "order" o2 ON so.order_id = o2.id
        WHERE 1=1 {where_sql}
        ORDER BY so.stockout_date DESC, so.id DESC
        LIMIT :limit OFFSET :offset""",  # nosec B608
        qty_sql_template="""SELECT COALESCE(SUM(so.quantity), 0)
        FROM stock_out so JOIN product p ON so.product_id = p.id
        LEFT JOIN "order" o2 ON so.order_id = o2.id
        WHERE 1=1 {where_sql}""",
        row_mapper=lambda row: {
            'record_id': row.record_id, 'record_no': row.record_no or '',
            'stockout_date': row.stockout_date or '-', 'customer': row.customer or '',
            'product_name': row.product_name or '', 'product_barcode': row.product_barcode or '',
            'quantity': row.quantity or 0, 'note': row.note or '',
        },
    )


@cache_result(
    key_prefix='reports:deduction_logs',
    ttl=30,
    local_ttl=10,
    key_builder=lambda *args, **kwargs: f"c:{kwargs.get('customer','')}:p:{kwargs.get('product','')}:s:{kwargs.get('status','')}:f:{kwargs.get('factory','')}:sd:{kwargs.get('start_date','')}:ed:{kwargs.get('end_date','')}:pg:{kwargs.get('page',1)}:pp:{kwargs.get('per_page',20)}",
)
async def get_deduction_logs(db: AsyncSession, customer: str = '', product: str = '',
                              start_date: str = '', end_date: str = '',
                              page: int = 1, per_page: int = 20, factory: str = '') -> dict:
    """备货抵扣流水（stockin_id IS NOT NULL，COUNT(*) OVER() 合并计数查询）"""
    per_page = min(max(1, per_page), 100)
    customer = customer.strip()[:100]
    product = product.strip()[:100]

    where_clauses = ["so.stockin_id IS NOT NULL",
                     "(o.is_deleted = false OR o.is_deleted IS NULL)"]
    params: dict[str, object] = {}

    if customer:
        where_clauses.append("COALESCE(so.customer, '') LIKE :customer")
        params['customer'] = f'%{escape_like(customer)}%'
    if product:
        where_clauses.append("(COALESCE(p.name, '') LIKE :product OR COALESCE(p.barcode, '') LIKE :product)")
        params['product'] = f'%{escape_like(product)}%'
    if factory:
        where_clauses.append("p.factory = :factory")
        params['factory'] = factory
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
        so.id AS record_id, so.stockout_no AS record_no,
        to_char(so.stockout_date, 'YYYY-MM-DD HH24:MI') AS deduction_time,
        to_char(so.stockout_date, 'YYYY-MM-DD HH24:MI') AS stockout_date,
        so.customer, p.name AS product_name, p.barcode AS product_barcode,
        (so.quantity - so.returned_quantity) AS quantity,
        so.quantity AS gross_quantity, so.note AS stockout_note,
        o.order_no AS order_no, o.note AS order_note,
        COUNT(*) OVER() AS total_count
        FROM stock_out so JOIN product p ON so.product_id = p.id
        LEFT JOIN {order_tbl} o ON so.order_id = o.id
        WHERE 1=1 {{where_sql}}
        ORDER BY so.stockout_date DESC, so.id DESC
        LIMIT :limit OFFSET :offset""",  # nosec B608
        qty_sql_template=f"""SELECT COALESCE(SUM(so.quantity - so.returned_quantity), 0)
        FROM stock_out so JOIN product p ON so.product_id = p.id
        LEFT JOIN {order_tbl} o ON so.order_id = o.id
        WHERE 1=1 {{where_sql}}""",  # nosec B608
        row_mapper=lambda row: {
            'record_id': row.record_id, 'record_no': row.record_no or '',
            'deduction_time': row.deduction_time or '-', 'customer': row.customer or '',
            'product_name': row.product_name or '', 'product_barcode': row.product_barcode or '',
            'quantity': row.quantity or 0,
            # 行内编辑需要「毛量」与「出货日期/真备注」（quantity 是净量，直接回写会把毛量改错）
            'gross_quantity': row.gross_quantity or 0,
            'stockout_date': row.stockout_date or '-',
            'note': row.stockout_note or '',
            'order_no': row.order_no or '', 'order_note': row.order_note or '',
        },
    )
