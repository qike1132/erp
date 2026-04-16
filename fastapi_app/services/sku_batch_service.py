"""SKU批次管理服务层"""
from sqlalchemy import select, func, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from fastapi_app.shared_models import SkuBatch
from fastapi_app.services import escape_like

# 允许排序的字段白名单，防止任意属性访问
SORTABLE_COLUMNS = {
    'sku_code': SkuBatch.sku_code,
    'batch_no': SkuBatch.batch_no,
    'create_time': SkuBatch.create_time,
    'status': SkuBatch.status,
    'quantity': SkuBatch.quantity,
    'update_time': SkuBatch.update_time,
}


async def get_sku_batches(
    db: AsyncSession,
    page: int = 1,
    per_page: int = 20,
    batch_no: str = '',
    sku_code: str = '',
    status: str = '',
    start_date: str = '',
    end_date: str = '',
    sort_by: str = 'create_time',
    sort_order: str = 'desc',
) -> dict:
    """查询SKU批次列表"""
    query = select(SkuBatch)
    count_query = select(func.count()).select_from(SkuBatch)

    # 筛选条件
    if batch_no:
        query = query.where(SkuBatch.batch_no.like(f'%{escape_like(batch_no)}%'))
        count_query = count_query.where(SkuBatch.batch_no.like(f'%{escape_like(batch_no)}%'))
    if sku_code:
        query = query.where(SkuBatch.sku_code.like(f'%{escape_like(sku_code)}%'))
        count_query = count_query.where(SkuBatch.sku_code.like(f'%{escape_like(sku_code)}%'))
    if status:
        query = query.where(SkuBatch.status == status)
        count_query = count_query.where(SkuBatch.status == status)
    if start_date:
        try:
            sd = datetime.strptime(start_date, '%Y-%m-%d')
            query = query.where(SkuBatch.create_time >= sd)
            count_query = count_query.where(SkuBatch.create_time >= sd)
        except ValueError:
            pass
    if end_date:
        try:
            ed = datetime.strptime(end_date, '%Y-%m-%d')
            ed = ed.replace(hour=23, minute=59, second=59)
            query = query.where(SkuBatch.create_time <= ed)
            count_query = count_query.where(SkuBatch.create_time <= ed)
        except ValueError:
            pass

    # 排序 - 使用白名单校验，防止任意属性访问
    sort_column = SORTABLE_COLUMNS.get(sort_by, SkuBatch.create_time)
    if sort_order == 'asc':
        query = query.order_by(sort_column.asc())
    else:
        query = query.order_by(sort_column.desc())

    # 总数
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # 分页
    pages = (total + per_page - 1) // per_page if total > 0 else 0
    query = query.offset((page - 1) * per_page).limit(per_page)

    result = await db.execute(query)
    batches = result.scalars().all()

    return {
        'success': True,
        'items': [b.to_dict() for b in batches],
        'total': total,
        'pages': pages,
        'current_page': page,
    }


async def get_sku_batch_stats(db: AsyncSession) -> dict:
    """获取批次统计数据"""
    total_result = await db.execute(select(func.count()).select_from(SkuBatch))
    total = total_result.scalar() or 0

    active_result = await db.execute(
        select(func.count()).select_from(SkuBatch).where(SkuBatch.status == 'active')
    )
    active = active_result.scalar() or 0

    frozen_result = await db.execute(
        select(func.count()).select_from(SkuBatch).where(SkuBatch.status == 'frozen')
    )
    frozen = frozen_result.scalar() or 0

    expired_result = await db.execute(
        select(func.count()).select_from(SkuBatch).where(SkuBatch.status == 'expired')
    )
    expired = expired_result.scalar() or 0

    return {
        'success': True,
        'total': total,
        'active': active,
        'frozen': frozen,
        'expired': expired,
    }
