"""财务统计服务层"""
import logging
from datetime import datetime, timedelta
from sqlalchemy import text

from fastapi_app.services import escape_like

logger = logging.getLogger(__name__)


async def get_customer_summary(db, customer: str = '', start_date: str = '',
                               end_date: str = '', page: int = 1,
                               per_page: int = 20) -> dict:
    """按客户汇总出货数量和金额（仅手动出货，stockin_id IS NULL）"""
    per_page = min(max(1, per_page), 100)
    customer = customer.strip()[:100]

    where_clauses = ["so.quantity > 0", "so.stockin_id IS NULL"]
    params = {}

    if customer:
        where_clauses.append("COALESCE(so.customer, '') LIKE :customer")
        params['customer'] = f'%{escape_like(customer)}%'
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

    # 总数
    count_sql = f"""SELECT COUNT(*) FROM (
        SELECT so.customer
        FROM stock_out so JOIN product p ON so.product_id = p.id
        WHERE 1=1 {where_sql}
        GROUP BY so.customer
    ) AS grouped"""
    total = (await db.execute(text(count_sql), params)).scalar() or 0

    # 数据
    data_sql = f"""SELECT
        COALESCE(so.customer, '未知客户') AS customer,
        SUM(so.quantity) AS total_quantity,
        SUM(so.quantity * COALESCE(p.price, 0)) AS total_amount,
        COUNT(so.id) AS stockout_count
        FROM stock_out so JOIN product p ON so.product_id = p.id
        WHERE 1=1 {where_sql}
        GROUP BY so.customer
        ORDER BY total_amount DESC
        LIMIT :limit OFFSET :offset"""
    params['limit'] = per_page
    params['offset'] = (page - 1) * per_page

    results = (await db.execute(text(data_sql), params)).fetchall()

    logs = []
    for row in results:
        logs.append({
            'customer': row.customer,
            'total_quantity': row.total_quantity,
            'total_amount': float(row.total_amount) if row.total_amount else 0.0,
            'stockout_count': row.stockout_count,
        })

    # 汇总统计
    stats_sql = f"""SELECT
        COALESCE(SUM(so.quantity), 0) AS total_quantity,
        COALESCE(SUM(so.quantity * COALESCE(p.price, 0)), 0) AS total_amount
        FROM stock_out so JOIN product p ON so.product_id = p.id
        WHERE 1=1 {where_sql}"""
    stats_params = {k: v for k, v in params.items() if k not in ('limit', 'offset')}
    stats_row = (await db.execute(text(stats_sql), stats_params)).fetchone()

    return {
        'success': True,
        'logs': logs,
        'stats': {
            'total_count': total,
            'total_quantity': stats_row.total_quantity if stats_row else 0,
            'total_amount': float(stats_row.total_amount) if stats_row and stats_row.total_amount else 0.0,
        },
        'pagination': {
            'page': page, 'per_page': per_page,
            'total': total,
            'pages': (total + per_page - 1) // per_page if per_page else 0,
        },
    }


async def get_daily_amount(db, customer: str = '', start_date: str = '',
                            end_date: str = '', page: int = 1,
                            per_page: int = 20) -> dict:
    """按日汇总出货金额（仅手动出货，stockin_id IS NULL）"""
    per_page = min(max(1, per_page), 100)
    customer = customer.strip()[:100]

    where_clauses = ["so.quantity > 0", "so.stockin_id IS NULL"]
    params = {}

    if customer:
        where_clauses.append("COALESCE(so.customer, '') LIKE :customer")
        params['customer'] = f'%{escape_like(customer)}%'
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

    # 总数
    count_sql = f"""SELECT COUNT(*) FROM (
        SELECT DATE(so.stockout_date)
        FROM stock_out so JOIN product p ON so.product_id = p.id
        WHERE 1=1 {where_sql}
        GROUP BY DATE(so.stockout_date)
    ) AS grouped"""
    total = (await db.execute(text(count_sql), params)).scalar() or 0

    # 数据
    data_sql = f"""SELECT
        DATE(so.stockout_date) AS stockout_date_only,
        SUM(so.quantity) AS total_quantity,
        SUM(so.quantity * COALESCE(p.price, 0)) AS total_amount,
        COUNT(so.id) AS stockout_count,
        GROUP_CONCAT(DISTINCT COALESCE(so.customer, '未知客户') ORDER BY so.customer SEPARATOR '、') AS customer_names
        FROM stock_out so JOIN product p ON so.product_id = p.id
        WHERE 1=1 {where_sql}
        GROUP BY DATE(so.stockout_date)
        ORDER BY DATE(so.stockout_date) DESC
        LIMIT :limit OFFSET :offset"""
    params['limit'] = per_page
    params['offset'] = (page - 1) * per_page

    results = (await db.execute(text(data_sql), params)).fetchall()

    logs = []
    for row in results:
        logs.append({
            'date': row.stockout_date_only.strftime('%Y-%m-%d') if row.stockout_date_only else '-',
            'total_quantity': row.total_quantity,
            'total_amount': float(row.total_amount) if row.total_amount else 0.0,
            'stockout_count': row.stockout_count,
            'customer_names': row.customer_names or '',
        })

    # 汇总统计
    stats_sql = f"""SELECT
        COALESCE(SUM(so.quantity), 0) AS total_quantity,
        COALESCE(SUM(so.quantity * COALESCE(p.price, 0)), 0) AS total_amount
        FROM stock_out so JOIN product p ON so.product_id = p.id
        WHERE 1=1 {where_sql}"""
    stats_params = {k: v for k, v in params.items() if k not in ('limit', 'offset')}
    stats_row = (await db.execute(text(stats_sql), stats_params)).fetchone()

    return {
        'success': True,
        'logs': logs,
        'stats': {
            'total_count': total,
            'total_quantity': stats_row.total_quantity if stats_row else 0,
            'total_amount': float(stats_row.total_amount) if stats_row and stats_row.total_amount else 0.0,
        },
        'pagination': {
            'page': page, 'per_page': per_page,
            'total': total,
            'pages': (total + per_page - 1) // per_page if per_page else 0,
        },
    }


async def get_daily_amount_chart(db, customer: str = '', start_date: str = '',
                                  end_date: str = '') -> dict:
    """按日汇总出货金额（图表用，不分页，按日期正序）"""
    customer = customer.strip()[:100]

    where_clauses = ["so.quantity > 0", "so.stockin_id IS NULL"]
    params = {}

    if customer:
        where_clauses.append("COALESCE(so.customer, '') LIKE :customer")
        params['customer'] = f'%{escape_like(customer)}%'
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

    data_sql = f"""SELECT
        DATE(so.stockout_date) AS stockout_date_only,
        SUM(so.quantity) AS total_quantity,
        SUM(so.quantity * COALESCE(p.price, 0)) AS total_amount
        FROM stock_out so JOIN product p ON so.product_id = p.id
        WHERE 1=1 {where_sql}
        GROUP BY DATE(so.stockout_date)
        ORDER BY DATE(so.stockout_date) ASC"""

    results = (await db.execute(text(data_sql), params)).fetchall()

    dates = []
    quantities = []
    amounts = []
    for row in results:
        dates.append(row.stockout_date_only.strftime('%Y-%m-%d') if row.stockout_date_only else '-')
        quantities.append(row.total_quantity)
        amounts.append(float(row.total_amount) if row.total_amount else 0.0)

    return {
        'success': True,
        'chart': {
            'dates': dates,
            'quantities': quantities,
            'amounts': amounts,
        }
    }
