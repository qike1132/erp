"""
采购中心 - 修改历史 & 保存查询 & 状态日志

从 purchase_center_service.py 拆分。
"""
import json
import logging
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.sanitizer import escape_like
from fastapi_app.shared_models import ModificationLog, OrderStatusLog, SavedQuery

logger = logging.getLogger(__name__)


async def get_modification_logs(db: AsyncSession, *, target_type: str = '', target_id: int = 0,
                                page: int = 1, per_page: int = 20) -> dict:
    query = select(ModificationLog)
    count_query = select(func.count(ModificationLog.id))
    if target_type:
        query = query.where(ModificationLog.target_type == target_type)
        count_query = count_query.where(ModificationLog.target_type == target_type)
    if target_id:
        query = query.where(ModificationLog.target_id == target_id)
        count_query = count_query.where(ModificationLog.target_id == target_id)
    query = query.order_by(ModificationLog.modify_time.desc())

    total_result = await db.execute(count_query)
    total = total_result.scalar()

    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    logs = result.scalars().all()
    return {
        'logs': [log.to_dict() for log in logs],
        'total': total,
    }


async def get_saved_queries(db: AsyncSession, query_type: str = 'purchase_order', user_id: int = 1) -> list:
    result = await db.execute(
        select(SavedQuery).where(
            SavedQuery.query_type == query_type,
            SavedQuery.creator_id == user_id,
        ).order_by(SavedQuery.create_time.desc())
    )
    queries = result.scalars().all()
    return [q.to_dict() for q in queries]


async def save_query(db: AsyncSession, data: dict, user_id: int, username: str) -> dict:
    sq = SavedQuery(
        name=data['name'],
        query_type=data.get('query_type', 'purchase_order'),
        conditions=json.dumps(data['conditions'], ensure_ascii=False),
        creator_id=user_id,
        creator_name=username,
    )
    db.add(sq)
    return sq.to_dict()


async def delete_saved_query(db: AsyncSession, query_id: int) -> str | None:
    sq = await db.get(SavedQuery, query_id)
    if not sq:
        return None
    await db.delete(sq)
    return '已删除'


async def use_saved_query(db: AsyncSession, query_id: int) -> dict | None:
    sq = await db.get(SavedQuery, query_id)
    if not sq:
        return None
    sq.use_count += 1
    sq.last_use_time = datetime.now(UTC).replace(tzinfo=None)
    return sq.to_dict()


async def get_status_logs(db: AsyncSession, *, target_type: str = '', target_id: int = 0,
                          order_no: str = '', page: int = 1, per_page: int = 20) -> dict:
    query = select(OrderStatusLog)
    count_query = select(func.count(OrderStatusLog.id))
    if target_type:
        query = query.where(OrderStatusLog.target_type == target_type)
        count_query = count_query.where(OrderStatusLog.target_type == target_type)
    if target_id:
        query = query.where(OrderStatusLog.target_id == target_id)
        count_query = count_query.where(OrderStatusLog.target_id == target_id)
    if order_no:
        query = query.where(OrderStatusLog.order_no.ilike(f'%{escape_like(order_no)}%'))  # sql-safe: escape_like/绑定参数/常量片段
        count_query = count_query.where(OrderStatusLog.order_no.ilike(f'%{escape_like(order_no)}%'))  # sql-safe: escape_like/绑定参数/常量片段
    query = query.order_by(OrderStatusLog.action_time.desc())

    total_result = await db.execute(count_query)
    total = total_result.scalar()

    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    logs = result.scalars().all()
    return {
        'logs': [log.to_dict() for log in logs],
        'total': total,
    }
