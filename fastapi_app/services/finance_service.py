"""财务统计服务层

SECURITY NOTE: where_clauses 列表仅包含硬编码的 SQL 片段，
禁止将用户输入直接拼接到 where_clauses 中，所有用户输入
必须通过 :param 参数绑定传递，以防止 SQL 注入。
"""
import logging
from datetime import datetime, timedelta
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any

from fastapi_app.services import escape_like
from fastapi_app.shared_models import Product, StockOut

logger = logging.getLogger(__name__)


def _normalize_finance_filters(customer: str = '', start_date: str = '', end_date: str = '') -> tuple[list, str]:
    customer = customer.strip()[:100]
    filters = [
        StockOut.quantity > 0,
        StockOut.stockin_id.is_(None),
    ]

    if customer:
        filters.append(
            func.coalesce(StockOut.customer, '').like(
                f'%{escape_like(customer)}%',
                escape='\\',
            )
        )
    if start_date:
        try:
            filters.append(StockOut.stockout_date >= datetime.strptime(start_date, '%Y-%m-%d'))
        except ValueError:
            pass
    if end_date:
        try:
            filters.append(StockOut.stockout_date < datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1))
        except ValueError:
            pass

    return filters, customer


def _amount_expr():
    return StockOut.quantity * func.coalesce(Product.price, 0)


def _daily_date_expr():
    return func.date(StockOut.stockout_date)


async def _get_finance_stats(db: AsyncSession, filters: list) -> tuple[int, float]:
    stats_stmt = (
        select(
            func.coalesce(func.sum(StockOut.quantity), 0).label('total_quantity'),
            func.coalesce(func.sum(_amount_expr()), 0).label('total_amount'),
        )
        .select_from(StockOut)
        .join(Product, StockOut.product_id == Product.id)
        .where(*filters)
    )
    stats_row = (await db.execute(stats_stmt)).fetchone()
    return (
        stats_row.total_quantity if stats_row else 0,
        float(stats_row.total_amount) if stats_row and stats_row.total_amount else 0.0,
    )


async def get_customer_summary(db: AsyncSession, customer: str = '', start_date: str = '',
                               end_date: str = '', page: int = 1,
                               per_page: int = 20) -> dict:
    """按客户汇总出货数量和金额（仅手动出货，stockin_id IS NULL）"""
    per_page = min(max(1, per_page), 100)
    filters, customer = _normalize_finance_filters(customer, start_date, end_date)
    customer_expr = func.coalesce(StockOut.customer, '未知客户')
    grouped_stmt = (
        select(
            customer_expr.label('customer'),
            func.sum(StockOut.quantity).label('total_quantity'),
            func.sum(_amount_expr()).label('total_amount'),
            func.count(StockOut.id).label('stockout_count'),
        )
        .select_from(StockOut)
        .join(Product, StockOut.product_id == Product.id)
        .where(*filters)
        .group_by(customer_expr)
    )
    count_stmt = select(func.count()).select_from(
        select(customer_expr)
        .select_from(StockOut)
        .join(Product, StockOut.product_id == Product.id)
        .where(*filters)
        .group_by(customer_expr)
        .subquery()
    )
    total = (await db.execute(count_stmt)).scalar() or 0

    results = (
        await db.execute(
            grouped_stmt
            .order_by(func.sum(_amount_expr()).desc())
            .limit(per_page)
            .offset((page - 1) * per_page)
        )
    ).fetchall()

    logs = []
    for row in results:
        logs.append({
            'customer': row.customer,
            'total_quantity': row.total_quantity,
            'total_amount': float(row.total_amount) if row.total_amount else 0.0,
            'stockout_count': row.stockout_count,
        })

    total_quantity, total_amount = await _get_finance_stats(db, filters)

    return {
        'success': True,
        'logs': logs,
        'stats': {
            'total_count': total,
            'total_quantity': total_quantity,
            'total_amount': total_amount,
        },
        'pagination': {
            'page': page, 'per_page': per_page,
            'total': total,
            'pages': (total + per_page - 1) // per_page if per_page else 0,
        },
    }


async def get_daily_amount(db: AsyncSession, customer: str = '', start_date: str = '',
                            end_date: str = '', page: int = 1,
                            per_page: int = 20) -> dict:
    """按日汇总出货金额（仅手动出货，stockin_id IS NULL）"""
    per_page = min(max(1, per_page), 100)
    filters, customer = _normalize_finance_filters(customer, start_date, end_date)
    date_expr = _daily_date_expr()
    grouped_stmt = (
        select(
            date_expr.label('stockout_date_only'),
            func.sum(StockOut.quantity).label('total_quantity'),
            func.sum(_amount_expr()).label('total_amount'),
            func.count(StockOut.id).label('stockout_count'),
        )
        .select_from(StockOut)
        .join(Product, StockOut.product_id == Product.id)
        .where(*filters)
        .group_by(date_expr)
    )
    count_stmt = select(func.count()).select_from(
        select(date_expr)
        .select_from(StockOut)
        .join(Product, StockOut.product_id == Product.id)
        .where(*filters)
        .group_by(date_expr)
        .subquery()
    )
    total = (await db.execute(count_stmt)).scalar() or 0
    results = (
        await db.execute(
            grouped_stmt
            .order_by(date_expr.desc())
            .limit(per_page)
            .offset((page - 1) * per_page)
        )
    ).fetchall()

    page_dates = [row.stockout_date_only for row in results if row.stockout_date_only is not None]
    customer_names_by_date: dict[Any, list[str]] = {}
    if page_dates:
        customer_rows = (
            await db.execute(
                select(
                    date_expr.label('stockout_date_only'),
                    func.coalesce(StockOut.customer, '未知客户').label('customer_name'),
                )
                .select_from(StockOut)
                .join(Product, StockOut.product_id == Product.id)
                .where(*filters, date_expr.in_(page_dates))
                .distinct()
                .order_by(date_expr.desc(), func.coalesce(StockOut.customer, '未知客户').asc())
            )
        ).fetchall()
        for row in customer_rows:
            customer_names_by_date.setdefault(row.stockout_date_only, []).append(row.customer_name)

    logs = []
    for row in results:
        logs.append({
            'date': row.stockout_date_only.strftime('%Y-%m-%d') if row.stockout_date_only else '-',
            'total_quantity': row.total_quantity,
            'total_amount': float(row.total_amount) if row.total_amount else 0.0,
            'stockout_count': row.stockout_count,
            'customer_names': '、'.join(customer_names_by_date.get(row.stockout_date_only, [])),
        })

    total_quantity, total_amount = await _get_finance_stats(db, filters)

    return {
        'success': True,
        'logs': logs,
        'stats': {
            'total_count': total,
            'total_quantity': total_quantity,
            'total_amount': total_amount,
        },
        'pagination': {
            'page': page, 'per_page': per_page,
            'total': total,
            'pages': (total + per_page - 1) // per_page if per_page else 0,
        },
    }


async def get_daily_amount_chart(db: AsyncSession, customer: str = '', start_date: str = '',
                                  end_date: str = '') -> dict:
    """按日汇总出货金额（图表用，不分页，按日期正序）"""
    filters, customer = _normalize_finance_filters(customer, start_date, end_date)
    date_expr = _daily_date_expr()
    results = (
        await db.execute(
            select(
                date_expr.label('stockout_date_only'),
                func.sum(StockOut.quantity).label('total_quantity'),
                func.sum(_amount_expr()).label('total_amount'),
            )
            .select_from(StockOut)
            .join(Product, StockOut.product_id == Product.id)
            .where(*filters)
            .group_by(date_expr)
            .order_by(date_expr.asc())
        )
    ).fetchall()

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
