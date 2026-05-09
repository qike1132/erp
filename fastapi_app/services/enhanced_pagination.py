"""
增强分页服务 - keyset分页 + 游标分页 + count优化

用于深翻页(OFFSET>10000)场景的性能优化。
OFFSET深翻页随页码线性衰减，keyset分页保持O(1)。
"""
import logging
from typing import Any, Sequence

from sqlalchemy import Select, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

OFFSET_THRESHOLD = 5000  # 超过此偏移量自动切换keyset分页


async def optimized_count(db: AsyncSession, base_query: Select, table_name: str | None = None) -> int:
    """优化COUNT查询 - 大表先用pg_class近似计数，足够精确则跳过COUNT(*)"""
    if table_name:
        try:
            approx_result = await db.execute(
                text("SELECT reltuples::bigint FROM pg_class WHERE relname = :t"),
                {"t": table_name},
            )
            approx = approx_result.scalar()
            if approx and approx > 1000:
                return approx
        except Exception:
            pass
    result = await db.execute(base_query)
    return result.scalar() or 0


async def paginate_with_keyset(
    db: AsyncSession,
    base_query: Select,
    page: int,
    per_page: int,
    count_query: Select | None = None,
    keyset_cursor: Any | None = None,
    cursor_column: Any | None = None,
    table_name: str | None = None,
) -> dict:
    """
    智能分页 - 自动选择OFFSET或keyset模式

    keyset_cursor: 上一页最后一条记录的游标值(如order_date)
    cursor_column: 游标列(如Order.order_date)
    """
    offset = max(0, (page - 1)) * per_page

    if count_query is not None:
        total = await optimized_count(db, count_query, table_name)
    else:
        total = 0

    if keyset_cursor is not None and cursor_column is not None:
        query = base_query.where(cursor_column < keyset_cursor).order_by(cursor_column.desc()).limit(per_page)
    elif offset > OFFSET_THRESHOLD and cursor_column is not None:
        logger.info("深翻页 offset=%d 超过阈值 %d，自动使用keyset近似分页", offset, OFFSET_THRESHOLD)
        subq = base_query.order_by(cursor_column.desc()).offset(offset).limit(1).subquery()
        cursor_subq_col = subq.c[cursor_column.key] if hasattr(cursor_column, 'key') else subq.c[0]
        subq_scalar = select(cursor_subq_col)
        query = base_query.where(cursor_column <= subq_scalar).order_by(cursor_column.desc()).limit(per_page)
    else:
        query = base_query.offset(offset).limit(per_page)

    result = await db.execute(query)
    items = result.scalars().unique().all()

    if not items and offset > OFFSET_THRESHOLD and cursor_column is not None:
        logger.info("keyset子查询返回空，fallback到OFFSET分页")
        query = base_query.order_by(cursor_column.desc()).offset(offset).limit(per_page)
        result = await db.execute(query)
        items = result.scalars().unique().all()

    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page) if total else 1,
        "has_next": page * per_page < total if total else len(items) == per_page,
    }


class CursorPage:
    """游标分页 - 适用于无限滚动/加载更多场景"""

    def __init__(self, per_page: int = 50):
        self.per_page = per_page
        self._cursor: Any = None

    async def fetch(
        self,
        db: AsyncSession,
        base_query: Select,
        cursor_column: Any,
        cursor_value: Any | None = None,
    ) -> dict:
        query = base_query.limit(self.per_page + 1)
        if cursor_value is not None:
            query = query.where(cursor_column < cursor_value)

        result = await db.execute(query)
        items = result.scalars().unique().all()

        has_more = len(items) > self.per_page
        if has_more:
            items = items[: self.per_page]

        next_cursor = None
        if has_more and items:
            last = items[-1]
            next_cursor = getattr(last, cursor_column.key, None)

        self._cursor = next_cursor
        return {
            "items": items,
            "has_more": has_more,
            "next_cursor": next_cursor,
            "per_page": self.per_page,
        }
