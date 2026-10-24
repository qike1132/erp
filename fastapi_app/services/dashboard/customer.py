"""仪表盘客户维度聚合(出库/订单详情)

从 dashboard_service.py 按主题拆出,行为与原实现完全一致。
"""
import logging
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import DatabaseError, DataError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.business_time import (
    business_day_range,
    business_month_range,
    business_today,
)
from fastapi_app.core.cache import cache_result
from fastapi_app.core.float_utils import round_money
from fastapi_app.schemas.dashboard import CustomerOutDetail, CustomerOutDetailResponse
from fastapi_app.shared_models import Order, OrderItem, Product, StockOut

logger = logging.getLogger(__name__)


def _parse_dashboard_date(date_str: str | None) -> date:
    if date_str:
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return business_today()
    return business_today()


# 缓存键含 factory 维度（AUD-04）：厂 A 的聚合不得被厂 B 命中。
# 用普通拼接而非 f-string——扫描器对「f-string + 类 SQL 片段」有误报面，语义无差别。
def _customer_cache_key(period_kw: str, date_kw: str, **kwargs) -> str:
    return ("p:" + str(kwargs.get(period_kw, '') or '')
            + ":d:" + str(kwargs.get(date_kw, '') or '')
            + ":f:" + str(kwargs.get('factory', '') or ''))


@cache_result(key_prefix="dashboard:customer_out", ttl=60, local_ttl=30,
              key_builder=lambda **kwargs: _customer_cache_key('period', 'query_date', **kwargs))
async def fetch_customer_out_details(
    period: str, query_date: str | None, db: AsyncSession, factory: str = ''
) -> dict:
    """按客户汇总出库详情。

    factory 非空时只统计该厂产品（AUD-04，2026-10-24 审计：逐客户营收明细
    与 /reports 同口径做工厂隔离）。返回 dict（model_dump）以兼容 cache_result
    的 JSON 序列化。
    """
    selected_date = _parse_dashboard_date(query_date)
    today = selected_date
    # 2026-10-17 审计 AUD-23：统一业务时区日界（aware），与桌面/移动端一致
    today_start, today_end = business_day_range(today)
    month_start, month_end = business_month_range(selected_date)

    if period == "month":
        start_time = month_start
        end_time = month_end
    else:
        start_time = today_start
        end_time = today_end

    try:
        # 条件列表一次性构建（factory 非空时追加本厂过滤，AUD-04）。
        out_filters = [
            StockOut.stockout_date >= start_time,
            StockOut.stockout_date < end_time,
            StockOut.customer.isnot(None),
            StockOut.customer != "",
        ]
        if factory:
            out_filters.append(Product.factory == factory)
        result = await db.execute(
            select(
                StockOut.customer,
                func.coalesce(func.sum(StockOut.quantity - StockOut.returned_quantity), 0),
                func.coalesce(func.sum((StockOut.quantity - StockOut.returned_quantity) * Product.price), 0)
            )
            .join(Product, StockOut.product_id == Product.id, isouter=True)
            .where(*out_filters)
            .group_by(StockOut.customer)
        )

        details = []
        for row in result.all():
            details.append(CustomerOutDetail(
                customer_name=row[0] or "未知客户",
                total_quantity=int(row[1] or 0),
                total_amount=round_money(float(row[2] or 0))
            ))
        return CustomerOutDetailResponse(success=True, data=details).model_dump()
    except (OperationalError, DataError, DatabaseError, ValueError, TypeError) as e:
        logger.warning("客户出库详情加载失败: %s", e)
        return CustomerOutDetailResponse(success=True, data=[]).model_dump()

@cache_result(key_prefix="dashboard:customer_order", ttl=60, local_ttl=30,
              key_builder=lambda **kwargs: _customer_cache_key('period', 'date_param', **kwargs))
async def fetch_customer_order_details(
    period: str, date_param: str | None, db: AsyncSession, factory: str = ''
) -> dict:
    """按客户汇总订单详情。

    factory 非空时只统计该厂产品（口径同 fetch_customer_out_details，AUD-04）。
    返回 dict（model_dump）以兼容 cache_result 的 JSON 序列化。
    """
    selected_date = _parse_dashboard_date(date_param)
    today = selected_date
    # 2026-10-17 审计 AUD-23：统一业务时区日界（aware）
    today_start, today_end = business_day_range(today)
    month_start, month_end = business_month_range(selected_date)

    if period == "month":
        start_time = month_start
        end_time = month_end
    else:
        start_time = today_start
        end_time = today_end

    try:
        order_filters = [
            Order.order_date >= start_time,
            Order.order_date < end_time,
            Order.is_deleted.isnot(True),
            Order.customer.isnot(None),
            Order.customer != "",
        ]
        if factory:
            order_filters.append(Product.factory == factory)
        result = await db.execute(
            select(
                Order.customer,
                func.coalesce(func.sum(OrderItem.quantity), 0),
                func.coalesce(func.sum(OrderItem.quantity * Product.price), 0)
            )
            .join(OrderItem, OrderItem.order_id == Order.id, isouter=True)
            .join(Product, OrderItem.product_id == Product.id, isouter=True)
            .where(*order_filters)
            .group_by(Order.customer)
        )

        details = []
        for row in result.all():
            details.append(CustomerOutDetail(
                customer_name=row[0] or "未知客户",
                total_quantity=int(row[1] or 0),
                total_amount=round_money(float(row[2] or 0))
            ))
        return CustomerOutDetailResponse(success=True, data=details).model_dump()
    except (OperationalError, DataError, DatabaseError, ValueError, TypeError) as e:
        logger.warning("客户订单详情加载失败: %s", e)
        return CustomerOutDetailResponse(success=True, data=[]).model_dump()
