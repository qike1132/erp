"""皮套域共享辅助(日期/分页/过滤工具 + 常量)"""
import logging
from datetime import datetime

from fastapi_app.core.business_time import business_day_range
from fastapi_app.core.exceptions import BusinessError
from fastapi_app.utils import parse_date_strict

logger = logging.getLogger(__name__)

# 分页与搜索常量
DEFAULT_SEARCH_LIMIT = 20  # 无搜索关键词时返回的最大记录数
MAX_LIST_PAGE_SIZE = 100  # 列表查询每页数量上限
MAX_SUMMARY_PAGE_SIZE = 200  # 库存汇总每页数量上限


def _parse_date(date_str: str, field_name: str = "日期") -> datetime:
    """安全解析 YYYY-MM-DD 格式日期字符串。

    委托给共享工具函数 parse_date_strict，并将其 ValueError 转换为
    BusinessError（HTTP 400），便于前端友好提示。
    """
    try:
        return parse_date_strict(date_str, field_name)
    except ValueError as e:
        raise BusinessError(str(e)) from e


def _normalize_pagination(page: int, per_page: int, max_per_page: int) -> tuple[int, int]:
    """规范化分页参数（页码<1→1；每页<1→1，超过上限则截断）。"""
    page = max(1, page)
    per_page = max(1, min(per_page, max_per_page))
    return page, per_page


def _apply_date_filter(query, column, start_date: str, end_date: str, field_label: str):
    """为查询添加日期范围过滤条件（end_date 含当天）。

    M-41（2026-11-21 审计）：movement_date 是 timestamptz，naive 参数的正确性耦合在
    会话时区；统一走 business_day_range 的业务时区 aware 边界（end 侧 [次日 00:00)）。
    """
    if start_date:
        query = query.where(column >= business_day_range(_parse_date(start_date, field_label))[0])
    if end_date:
        query = query.where(column < business_day_range(_parse_date(end_date, field_label))[1])  # sql-safe: escape_like/绑定参数/常量片段
    return query


def _apply_quantity_filter(query, column, quantity_min: int | None, quantity_max: int | None):
    """为查询添加数量范围过滤条件（含端点）。"""
    if quantity_min is not None:
        query = query.where(column >= quantity_min)
    if quantity_max is not None:
        query = query.where(column <= quantity_max)
    return query
