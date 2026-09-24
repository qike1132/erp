"""皮套域共享辅助(日期/分页/过滤工具 + 常量)

从 case_service.py 按职责拆出,行为与原实现完全一致。
"""
import logging
from datetime import datetime, timedelta

from fastapi_app.core.exceptions import BusinessError
from fastapi_app.utils import parse_date_strict

logger = logging.getLogger(__name__)

# 分页与搜索常量
DEFAULT_SEARCH_LIMIT = 20  # 无搜索关键词时返回的最大记录数
MAX_LIST_PAGE_SIZE = 100  # 列表查询每页数量上限
MAX_SUMMARY_PAGE_SIZE = 200  # 库存汇总每页数量上限
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
