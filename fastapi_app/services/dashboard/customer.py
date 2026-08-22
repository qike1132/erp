"""仪表盘客户维度聚合(出库/订单详情)

从 dashboard_service.py 按主题拆出,行为与原实现完全一致。
"""
import logging
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import DatabaseError, DataError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.cache import cache_result
from fastapi_app.schemas.dashboard import CustomerOutDetail, CustomerOutDetailResponse
from fastapi_app.shared_models import Order, OrderItem, Product, StockOut

logger = logging.getLogger(__name__)


def _parse_dashboard_date(date_str: str | None) -> date:
    if date_str:
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return date.today()
    return date.today()

@cache_result(key_prefix="dashboard:customer_out", ttl=60, local_ttl=30,
              key_builder=lambda **kwargs: f"p:{kwargs.get('period', '')}:d:{kwargs.get('query_date', '') or ''}")  # sql-safe: escape_like/绑定参数/常量片段
async def fetch_customer_out_details(
    period: str, query_date: str | None, db: AsyncSession
) -> dict:
    """按客户汇总出库详情。

    返回 dict（model_dump）以兼容 cache_result 的 JSON 序列化。
    """
    selected_date = _parse_dashboard_date(query_date)
    today = selected_date
    today_start = datetime(today.year, today.month, today.day, 0, 0, 0)
    tomorrow = today + timedelta(days=1)
    today_end = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0, 0, 0)
    month_start = datetime(selected_date.year, selected_date.month, 1, 0, 0, 0)

    if period == "month":
        start_time = month_start
        end_time = datetime(selected_date.year, selected_date.month + 1, 1, 0, 0, 0) if selected_date.month < 12 else datetime(selected_date.year + 1, 1, 1, 0, 0, 0)
    else:
        start_time = today_start
        end_time = today_end

    try:
        result = await db.execute(
            select(
                StockOut.customer,
                func.coalesce(func.sum(StockOut.quantity), 0),
                func.coalesce(func.sum(StockOut.quantity * Product.price), 0)
            )
            .join(Product, StockOut.product_id == Product.id, isouter=True)
            .where(StockOut.stockout_date >= start_time)
            .where(StockOut.stockout_date < end_time)
            .where(StockOut.customer.isnot(None))
            .where(StockOut.customer != "")
            .group_by(StockOut.customer)
        )

        details = []
        for row in result.all():
            details.append(CustomerOutDetail(
                customer_name=row[0] or "未知客户",
                total_quantity=int(row[1] or 0),
                total_amount=round(float(row[2] or 0), 2)
            ))
        return CustomerOutDetailResponse(success=True, data=details).model_dump()
    except (OperationalError, DataError, DatabaseError, ValueError, TypeError) as e:
        logger.warning("客户出库详情加载失败: %s", e)
        return CustomerOutDetailResponse(success=True, data=[]).model_dump()

@cache_result(key_prefix="dashboard:customer_order", ttl=60, local_ttl=30,
              key_builder=lambda **kwargs: f"p:{kwargs.get('period', '')}:d:{kwargs.get('date_param', '') or ''}")
async def fetch_customer_order_details(
    period: str, date_param: str | None, db: AsyncSession
) -> dict:
    """按客户汇总订单详情。

    返回 dict（model_dump）以兼容 cache_result 的 JSON 序列化。
    """
    selected_date = _parse_dashboard_date(date_param)
    today = selected_date
    today_start = datetime(today.year, today.month, today.day, 0, 0, 0)
    tomorrow = today + timedelta(days=1)
    today_end = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0, 0, 0)
    month_start = datetime(selected_date.year, selected_date.month, 1, 0, 0, 0)

    if period == "month":
        start_time = month_start
        end_time = datetime(selected_date.year, selected_date.month + 1, 1, 0, 0, 0) if selected_date.month < 12 else datetime(selected_date.year + 1, 1, 1, 0, 0, 0)
    else:
        start_time = today_start
        end_time = today_end

    try:
        result = await db.execute(
            select(
                Order.customer,
                func.coalesce(func.sum(OrderItem.quantity), 0),
                func.coalesce(func.sum(OrderItem.quantity * Product.price), 0)
            )
            .join(OrderItem, OrderItem.order_id == Order.id, isouter=True)
            .join(Product, OrderItem.product_id == Product.id, isouter=True)
            .where(Order.order_date >= start_time)
            .where(Order.order_date < end_time)
            .where(Order.is_deleted.isnot(True))
            .where(Order.customer.isnot(None))
            .where(Order.customer != "")
            .group_by(Order.customer)
        )

        details = []
        for row in result.all():
            details.append(CustomerOutDetail(
                customer_name=row[0] or "未知客户",
                total_quantity=int(row[1] or 0),
                total_amount=round(float(row[2] or 0), 2)
            ))
        return CustomerOutDetailResponse(success=True, data=details).model_dump()
    except (OperationalError, DataError, DatabaseError, ValueError, TypeError) as e:
        logger.warning("客户订单详情加载失败: %s", e)
        return CustomerOutDetailResponse(success=True, data=[]).model_dump()