"""报表统计服务层"""
import logging
from datetime import datetime, timedelta
from sqlalchemy import select, func, text, or_
from sqlalchemy.orm import joinedload

from fastapi_app.shared_models import StockOut, StockIn, Order, Product

logger = logging.getLogger(__name__)


async def get_order_logs(db, customer: str = '', product: str = '', status: str = '',
                         start_date: str = '', end_date: str = '',
                         page: int = 1, per_page: int = 20) -> dict:
    """订单流水（分页+分组聚合）"""
    per_page = min(max(1, per_page), 100)
    customer = customer.strip()[:100]
    product = product.strip()[:100]

    where_clauses = []
    params = {}

    if customer:
        where_clauses.append("o.customer LIKE :customer")
        params['customer'] = f'%{customer}%'
    if product:
        where_clauses.append("(p.name LIKE :product OR p.barcode LIKE :product)")
        params['product'] = f'%{product}%'
    if status:
        valid = ['待备货', '部分备货', '已备货', '待出货', '已出货', '已取消']
        if status in valid:
            where_clauses.append("o.status = :status")
            params['status'] = status
    if start_date:
        try:
            params['start_date'] = datetime.strptime(start_date, '%Y-%m-%d')
            where_clauses.append("o.order_date >= :start_date")
        except ValueError:
            pass
    if end_date:
        try:
            params['end_date'] = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
            where_clauses.append("o.order_date < :end_date")
        except ValueError:
            pass

    where_sql = " AND " + " AND ".join(where_clauses) if where_clauses else ""

    # 总数
    count_sql = f"""SELECT COUNT(*) FROM (
        SELECT DATE(o.order_date), o.customer, p.name, p.barcode, o.status
        FROM `order` o JOIN product p ON o.product_id = p.id
        WHERE 1=1 {where_sql}
        GROUP BY DATE(o.order_date), o.customer, p.name, p.barcode, o.status
    ) AS grouped"""
    total = (await db.execute(text(count_sql), params)).scalar() or 0

    # 数据
    data_sql = f"""SELECT
        DATE(o.order_date) as order_date_only, o.customer, p.name as product_name,
        p.barcode as product_barcode, o.status,
        SUM(o.quantity) as total_quantity, COUNT(o.id) as order_count,
        GROUP_CONCAT(DISTINCT o.order_no ORDER BY o.order_no SEPARATOR ', ') as order_nos,
        GROUP_CONCAT(DISTINCT o.note ORDER BY o.id SEPARATOR '; ') as notes
        FROM `order` o JOIN product p ON o.product_id = p.id
        WHERE 1=1 {where_sql}
        GROUP BY DATE(o.order_date), o.customer, p.name, p.barcode, o.status
        ORDER BY DATE(o.order_date) DESC
        LIMIT :limit OFFSET :offset"""
    params['limit'] = per_page
    params['offset'] = (page - 1) * per_page

    results = (await db.execute(text(data_sql), params)).fetchall()

    logs = []
    for row in results:
        logs.append({
            'order_date': row.order_date_only.strftime('%Y-%m-%d') if row.order_date_only else '-',
            'customer': row.customer, 'product_name': row.product_name,
            'product_barcode': row.product_barcode or '',
            'quantity': row.total_quantity, 'status': row.status,
            'order_count': row.order_count,
            'order_nos': row.order_nos or '', 'note': row.notes or '',
        })

    total_qty = (await db.execute(text("SELECT SUM(quantity) FROM `order`"))).scalar() or 0

    return {
        'logs': logs,
        'stats': {'total_count': total, 'total_quantity': total_qty},
        'pagination': {'page': page, 'per_page': per_page, 'total': total, 'pages': (total + per_page - 1) // per_page if per_page else 0},
    }


async def export_report_to_excel(db, report_type: str, customer: str = '', product: str = '',
                                  status: str = '', start_date: str = '', end_date: str = '') -> bytes:
    """导出报表为 Excel（内存缓冲区）

    复用 Flask 侧的 ReportExporter 工具类生成 Excel，
    通过同步线程执行避免阻塞事件循环。
    """
    import asyncio
    from app import create_app

    def _sync_export():
        app = create_app()
        with app.app_context():
            from app.routes.report import get_all_logs_data
            from utils.report_exporter import ReportExporter

            logs, stats = get_all_logs_data(
                report_type,
                customer=customer, product=product, status=status,
                start_date=start_date, end_date=end_date
            )

            if len(logs) > 10000:
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
            return output.getvalue()

    # 在线程池中执行同步的 Flask 操作
    loop = asyncio.get_event_loop()
    content = await loop.run_in_executor(None, _sync_export)
    return content


async def get_stockin_logs(db, customer: str = '', product: str = '',
                           start_date: str = '', end_date: str = '',
                           page: int = 1, per_page: int = 20) -> dict:
    """备货流水（分页+分组聚合）"""
    per_page = min(max(1, per_page), 100)
    customer = customer.strip()[:100]
    product = product.strip()[:100]

    where_clauses = []
    params = {}

    if customer:
        where_clauses.append("COALESCE(s.customer, '') LIKE :customer")
        params['customer'] = f'%{customer}%'
    if product:
        where_clauses.append("(COALESCE(p.name, '') LIKE :product OR COALESCE(p.barcode, '') LIKE :product)")
        params['product'] = f'%{product}%'
    if start_date:
        try:
            params['start_date'] = datetime.strptime(start_date, '%Y-%m-%d')
            where_clauses.append("s.stockin_date >= :start_date")
        except ValueError:
            pass
    if end_date:
        try:
            params['end_date'] = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
            where_clauses.append("s.stockin_date < :end_date")
        except ValueError:
            pass

    where_sql = " AND " + " AND ".join(where_clauses) if where_clauses else ""

    count_sql = f"""SELECT COUNT(*) FROM (
        SELECT DATE(s.stockin_date), s.customer, p.name, p.barcode
        FROM stock_in s JOIN product p ON s.product_id = p.id
        WHERE 1=1 {where_sql}
        GROUP BY DATE(s.stockin_date), s.customer, p.name, p.barcode
    ) AS grouped"""
    total = (await db.execute(text(count_sql), params)).scalar() or 0

    data_sql = f"""SELECT
        DATE(s.stockin_date) as stockin_date_only, s.customer, p.name as product_name,
        p.barcode as product_barcode,
        SUM(s.quantity) as total_quantity, COUNT(s.id) as stockin_count,
        GROUP_CONCAT(DISTINCT s.stockin_no ORDER BY s.stockin_no SEPARATOR ', ') as stockin_nos,
        GROUP_CONCAT(DISTINCT s.note ORDER BY s.id SEPARATOR '; ') as notes
        FROM stock_in s JOIN product p ON s.product_id = p.id
        WHERE 1=1 {where_sql}
        GROUP BY DATE(s.stockin_date), s.customer, p.name, p.barcode
        ORDER BY DATE(s.stockin_date) DESC
        LIMIT :limit OFFSET :offset"""
    params['limit'] = per_page
    params['offset'] = (page - 1) * per_page

    results = (await db.execute(text(data_sql), params)).fetchall()

    logs = []
    for row in results:
        logs.append({
            'stockin_date': row.stockin_date_only.strftime('%Y-%m-%d') if row.stockin_date_only else '-',
            'customer': row.customer, 'product_name': row.product_name,
            'product_barcode': row.product_barcode or '',
            'quantity': row.total_quantity, 'stockin_count': row.stockin_count,
            'stockin_nos': row.stockin_nos or '', 'note': row.notes or '',
        })

    total_qty = (await db.execute(text("SELECT SUM(quantity) FROM stock_in"))).scalar() or 0

    return {
        'logs': logs,
        'stats': {'total_count': total, 'total_quantity': total_qty},
        'pagination': {'page': page, 'per_page': per_page, 'total': total, 'pages': (total + per_page - 1) // per_page if per_page else 0},
    }


async def export_report_to_excel(db, report_type: str, customer: str = '', product: str = '',
                                  status: str = '', start_date: str = '', end_date: str = '') -> bytes:
    """导出报表为 Excel（内存缓冲区）

    复用 Flask 侧的 ReportExporter 工具类生成 Excel，
    通过同步线程执行避免阻塞事件循环。
    """
    import asyncio
    from app import create_app

    def _sync_export():
        app = create_app()
        with app.app_context():
            from app.routes.report import get_all_logs_data
            from utils.report_exporter import ReportExporter

            logs, stats = get_all_logs_data(
                report_type,
                customer=customer, product=product, status=status,
                start_date=start_date, end_date=end_date
            )

            if len(logs) > 10000:
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
            return output.getvalue()

    # 在线程池中执行同步的 Flask 操作
    loop = asyncio.get_event_loop()
    content = await loop.run_in_executor(None, _sync_export)
    return content


async def get_stockout_logs(db, customer: str = '', product: str = '',
                            start_date: str = '', end_date: str = '',
                            page: int = 1, per_page: int = 20) -> dict:
    """出货流水（仅手动出货，stockin_id IS NULL）"""
    per_page = min(max(1, per_page), 100)
    customer = customer.strip()[:100]
    product = product.strip()[:100]

    where_clauses = ["so.quantity > 0", "so.stockin_id IS NULL"]
    params = {}

    if customer:
        where_clauses.append("COALESCE(so.customer, '') LIKE :customer")
        params['customer'] = f'%{customer}%'
    if product:
        where_clauses.append("(COALESCE(p.name, '') LIKE :product OR COALESCE(p.barcode, '') LIKE :product)")
        params['product'] = f'%{product}%'
    if start_date:
        try:
            params['start_date'] = datetime.strptime(start_date, '%Y-%m-%d')
            where_clauses.append("so.stockout_date >= :start_date")
        except ValueError:
            pass
    if end_date:
        try:
            params['end_date'] = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
            where_clauses.append("so.stockout_date < :end_date")
        except ValueError:
            pass

    where_sql = " AND " + " AND ".join(where_clauses)

    count_sql = f"""SELECT COUNT(*) FROM (
        SELECT DATE(so.stockout_date), so.customer, p.name, p.barcode
        FROM stock_out so JOIN product p ON so.product_id = p.id
        WHERE 1=1 {where_sql}
        GROUP BY DATE(so.stockout_date), so.customer, p.name, p.barcode
    ) AS grouped"""
    total = (await db.execute(text(count_sql), params)).scalar() or 0

    data_sql = f"""SELECT
        DATE(so.stockout_date) as stockout_date_only, so.customer, p.name as product_name,
        p.barcode as product_barcode,
        SUM(so.quantity) as total_quantity, COUNT(so.id) as stockout_count,
        GROUP_CONCAT(DISTINCT so.stockout_no ORDER BY so.stockout_no SEPARATOR ', ') as stockout_nos,
        GROUP_CONCAT(DISTINCT so.note ORDER BY so.id SEPARATOR '; ') as notes
        FROM stock_out so JOIN product p ON so.product_id = p.id
        WHERE 1=1 {where_sql}
        GROUP BY DATE(so.stockout_date), so.customer, p.name, p.barcode
        ORDER BY DATE(so.stockout_date) DESC
        LIMIT :limit OFFSET :offset"""
    params['limit'] = per_page
    params['offset'] = (page - 1) * per_page

    results = (await db.execute(text(data_sql), params)).fetchall()

    logs = []
    for row in results:
        logs.append({
            'stockout_date': row.stockout_date_only.strftime('%Y-%m-%d') if row.stockout_date_only else '-',
            'customer': row.customer or '', 'product_name': row.product_name,
            'product_barcode': row.product_barcode or '',
            'quantity': row.total_quantity, 'stockout_count': row.stockout_count,
            'stockout_nos': row.stockout_nos or '', 'note': row.notes or '',
        })

    total_qty = (await db.execute(text(
        "SELECT SUM(quantity) FROM stock_out WHERE quantity > 0 AND stockin_id IS NULL"
    ))).scalar() or 0

    return {
        'logs': logs,
        'stats': {'total_count': total, 'total_quantity': total_qty},
        'pagination': {'page': page, 'per_page': per_page, 'total': total, 'pages': (total + per_page - 1) // per_page if per_page else 0},
    }


async def export_report_to_excel(db, report_type: str, customer: str = '', product: str = '',
                                  status: str = '', start_date: str = '', end_date: str = '') -> bytes:
    """导出报表为 Excel（内存缓冲区）

    复用 Flask 侧的 ReportExporter 工具类生成 Excel，
    通过同步线程执行避免阻塞事件循环。
    """
    import asyncio
    from app import create_app

    def _sync_export():
        app = create_app()
        with app.app_context():
            from app.routes.report import get_all_logs_data
            from utils.report_exporter import ReportExporter

            logs, stats = get_all_logs_data(
                report_type,
                customer=customer, product=product, status=status,
                start_date=start_date, end_date=end_date
            )

            if len(logs) > 10000:
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
            return output.getvalue()

    # 在线程池中执行同步的 Flask 操作
    loop = asyncio.get_event_loop()
    content = await loop.run_in_executor(None, _sync_export)
    return content


async def get_deduction_logs(db, customer: str = '', product: str = '',
                              start_date: str = '', end_date: str = '',
                              page: int = 1, per_page: int = 20) -> dict:
    """备货抵扣流水（stockin_id IS NOT NULL）"""
    per_page = min(max(1, per_page), 100)
    customer = customer.strip()[:100]
    product = product.strip()[:100]

    where_clauses = ["so.stockin_id IS NOT NULL"]
    params = {}

    if customer:
        where_clauses.append("COALESCE(so.customer, '') LIKE :customer")
        params['customer'] = f'%{customer}%'
    if product:
        where_clauses.append("(COALESCE(p.name, '') LIKE :product OR COALESCE(p.barcode, '') LIKE :product)")
        params['product'] = f'%{product}%'
    if start_date:
        try:
            params['start_date'] = datetime.strptime(start_date, '%Y-%m-%d')
            where_clauses.append("so.stockout_date >= :start_date")
        except ValueError:
            pass
    if end_date:
        try:
            params['end_date'] = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
            where_clauses.append("so.stockout_date < :end_date")
        except ValueError:
            pass

    where_sql = " AND " + " AND ".join(where_clauses)

    count_sql = f"""SELECT COUNT(*) FROM (
        SELECT DATE(so.stockout_date), so.customer, p.name, p.barcode
        FROM stock_out so JOIN product p ON so.product_id = p.id
        WHERE 1=1 {where_sql}
        GROUP BY DATE(so.stockout_date), so.customer, p.name, p.barcode
    ) AS grouped"""
    total = (await db.execute(text(count_sql), params)).scalar() or 0

    data_sql = f"""SELECT
        DATE(so.stockout_date) as deduction_date_only, so.customer, p.name as product_name,
        p.barcode as sku,
        SUM(so.quantity) as total_quantity, COUNT(so.id) as deduction_count,
        GROUP_CONCAT(DISTINCT o.order_no ORDER BY o.order_no SEPARATOR ', ') as order_nos,
        GROUP_CONCAT(DISTINCT o.note ORDER BY o.id SEPARATOR '; ') as order_notes
        FROM stock_out so JOIN product p ON so.product_id = p.id
        LEFT JOIN `order` o ON so.order_id = o.id
        WHERE 1=1 {where_sql}
        GROUP BY DATE(so.stockout_date), so.customer, p.name, p.barcode
        ORDER BY DATE(so.stockout_date) DESC
        LIMIT :limit OFFSET :offset"""
    params['limit'] = per_page
    params['offset'] = (page - 1) * per_page

    results = (await db.execute(text(data_sql), params)).fetchall()

    logs = []
    for row in results:
        logs.append({
            'deduction_time': row.deduction_date_only.strftime('%Y-%m-%d') if row.deduction_date_only else '-',
            'customer': row.customer or '', 'product_name': row.product_name,
            'sku': row.sku or '',
            'quantity': row.total_quantity, 'deduction_count': row.deduction_count,
            'order_nos': row.order_nos or '', 'order_note': row.order_notes or '',
        })

    total_qty = (await db.execute(text(
        "SELECT SUM(quantity) FROM stock_out WHERE stockin_id IS NOT NULL"
    ))).scalar() or 0

    return {
        'logs': logs,
        'stats': {'total_count': total, 'total_quantity': total_qty},
        'pagination': {'page': page, 'per_page': per_page, 'total': total, 'pages': (total + per_page - 1) // per_page if per_page else 0},
    }


async def export_report_to_excel(db, report_type: str, customer: str = '', product: str = '',
                                  status: str = '', start_date: str = '', end_date: str = '') -> bytes:
    """导出报表为 Excel（内存缓冲区）

    复用 Flask 侧的 ReportExporter 工具类生成 Excel，
    通过同步线程执行避免阻塞事件循环。
    """
    import asyncio
    from app import create_app

    def _sync_export():
        app = create_app()
        with app.app_context():
            from app.routes.report import get_all_logs_data
            from utils.report_exporter import ReportExporter

            logs, stats = get_all_logs_data(
                report_type,
                customer=customer, product=product, status=status,
                start_date=start_date, end_date=end_date
            )

            if len(logs) > 10000:
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
            return output.getvalue()

    # 在线程池中执行同步的 Flask 操作
    loop = asyncio.get_event_loop()
    content = await loop.run_in_executor(None, _sync_export)
    return content
