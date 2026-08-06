"""
客户管理服务（采购中心接入）

从 purchase_center_service.py 拆分，保留原始导入路径的向后兼容。
"""
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.sanitizer import escape_like
from fastapi_app.utils import calc_total_pages
from fastapi_app.shared_models import Customer

logger = logging.getLogger(__name__)


async def get_customers(db: AsyncSession, *, page: int = 1, per_page: int = 20,
                        status: str = 'all', keyword: str = '',
                        sort_by: str = 'name', sort_order: str = 'asc') -> dict:
    query = select(Customer)
    count_query = select(func.count(Customer.id))

    if status == 'active':
        query = query.where(Customer.status)
        count_query = count_query.where(Customer.status)
    elif status == 'inactive':
        query = query.where(~Customer.status)  
        count_query = count_query.where(~Customer.status)

    if keyword:
        query = query.where(Customer.name.ilike(f'%{escape_like(keyword)}%'))
        count_query = count_query.where(Customer.name.ilike(f'%{escape_like(keyword)}%'))

    sort_map = {
        'name': Customer.name,
        'create_time': Customer.create_time,
        'update_time': Customer.update_time,
    }
    sort_col = sort_map.get(sort_by, Customer.name)
    if sort_order == 'desc':
        sort_col = sort_col.desc()
    query = query.order_by(sort_col)

    total_result = await db.execute(count_query)
    total = total_result.scalar()

    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    customers = result.scalars().all()

    return {
        'customers': [
            {
                'id': c.id,
                'name': c.name,
                'status': c.status,
                'create_time': c.create_time.strftime('%Y-%m-%d %H:%M') if c.create_time else '',
                'update_time': c.update_time.strftime('%Y-%m-%d %H:%M') if c.update_time else '',
            }
            for c in customers
        ],
        'total': total,
        'pages': calc_total_pages(total, per_page),
        'current_page': page,
    }


async def get_customer_detail(db: AsyncSession, customer_id: int) -> dict:
    customer = await db.get(Customer, customer_id)
    if not customer:
        return None
    return {'id': customer.id, 'name': customer.name, 'status': customer.status}


async def batch_get_customers(db: AsyncSession, ids: list) -> list:
    if not ids:
        return []
    result = await db.execute(select(Customer).where(Customer.id.in_(ids)))
    customers = result.scalars().all()
    return [{'id': c.id, 'name': c.name} for c in customers]


async def get_customers_statistics(db: AsyncSession) -> dict:
    total_result = await db.execute(select(func.count(Customer.id)))
    total = total_result.scalar()

    active_result = await db.execute(
        select(func.count(Customer.id)).where(Customer.status == True)
    )
    active = active_result.scalar()

    recently_updated = 0
    if hasattr(Customer, 'update_time'):
        recent_result = await db.execute(
            select(func.count(Customer.id)).where(
                Customer.update_time >= datetime.now(UTC).replace(tzinfo=None) - timedelta(days=30)
            )
        )
        recently_updated = recent_result.scalar()

    return {
        'total': total,
        'active': active,
        'inactive': total - active,
        'recently_updated': recently_updated,
    }
