"""客户管理服务层"""
import logging

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.shared_models import Customer, CustomerAccessLog, Order, PurchaseOrder, PurchasePlan, StockIn, StockOut

logger = logging.getLogger(__name__)

_ACTIVE_CUSTOMER_CACHE_KEY = "active_customer_names"
_ACTIVE_CUSTOMER_CACHE_TTL = 300


async def get_customers(db: AsyncSession, status: str | None = None, page: int = 1, per_page: int = 50, search: str = '') -> dict:
    """获取客户列表（支持分页和搜索）"""
    query = select(Customer)
    count_query = select(func.count(Customer.id))
    if status == 'active':
        query = query.where(Customer.status)
        count_query = count_query.where(Customer.status)
    elif status == 'inactive':
        query = query.where(not Customer.status)
        count_query = count_query.where(not Customer.status)
    if search:
        escaped = search.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        like_pattern = f'%{escaped}%'
        query = query.where(or_(Customer.name.ilike(like_pattern), Customer.contact.ilike(like_pattern), Customer.phone.ilike(like_pattern)))
        count_query = count_query.where(or_(Customer.name.ilike(like_pattern), Customer.contact.ilike(like_pattern), Customer.phone.ilike(like_pattern)))
    total = (await db.execute(count_query)).scalar() or 0
    query = query.order_by(Customer.name).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    customers = list(result.scalars().all())
    return {'items': customers, 'total': total, 'page': page, 'per_page': per_page}


async def get_customer(db: AsyncSession, customer_id: int) -> Customer | None:
    """获取单个客户"""
    result = await db.execute(select(Customer).where(Customer.id == customer_id))
    return result.scalar_one_or_none()


async def search_customers(db: AsyncSession, query_str: str) -> list[Customer]:
    """搜索客户（按名称/联系人/电话模糊匹配，仅返回启用状态）

    委托至 customer_search_service 统一实现，再根据 ID 回查 ORM 对象
    以保持原有返回类型（list[Customer]）的向后兼容。
    """
    from fastapi_app.services.customer_search_service import customer_search_service

    results = await customer_search_service.search_active_customers(db, query_str, limit=20)

    if not results:
        return []

    customer_ids = [r["id"] for r in results]
    result = await db.execute(
        select(Customer).where(Customer.id.in_(customer_ids))
    )
    return list(result.scalars().all())


async def get_active_customer_names(db: AsyncSession) -> list[dict]:
    """获取所有启用客户名称列表（带Redis缓存5分钟）"""
    try:
        from utils.redis_cache import redis_cache
        cached = await redis_cache.get(_ACTIVE_CUSTOMER_CACHE_KEY)
        if cached:
            return cached
    except (OSError, ConnectionError, ValueError):
        logger.warning("客户名称缓存读取失败", exc_info=True)

    result = await db.execute(
        select(Customer).where(Customer.status).order_by(Customer.name)
    )
    data = [{'id': c.id, 'name': c.name} for c in result.scalars().all()]

    try:
        from utils.redis_cache import redis_cache
        await redis_cache.set(_ACTIVE_CUSTOMER_CACHE_KEY, data, timeout=_ACTIVE_CUSTOMER_CACHE_TTL)
    except (OSError, ValueError):
        logger.warning("客户名称缓存写入失败", exc_info=True)

    return data


async def create_customer(db: AsyncSession, name: str, contact: str | None, phone: str | None,
                          address: str | None, note: str | None) -> Customer:
    """创建客户"""
    result = await db.execute(select(Customer).where(Customer.name == name))
    if result.scalar_one_or_none():
        raise ValueError("客户名称已存在")

    customer = Customer(name=name, contact=contact, phone=phone, address=address, note=note, status=True)
    db.add(customer)
    await db.flush()
    await db.refresh(customer)
    await _invalidate_customer_cache()
    return customer


async def update_customer(db: AsyncSession, customer_id: int, name: str | None, contact: str | None,
                          phone: str | None, address: str | None, note: str | None,
                          status: bool | None) -> Customer:
    """更新客户"""
    customer = await db.get(Customer, customer_id)
    if not customer:
        raise ValueError("客户不存在")

    if name is not None:
        result = await db.execute(
            select(Customer).where(Customer.name == name, Customer.id != customer_id)
        )
        if result.scalar_one_or_none():
            raise ValueError("客户名称已存在")
        customer.name = name

    if contact is not None:
        customer.contact = contact
    if phone is not None:
        customer.phone = phone
    if address is not None:
        customer.address = address
    if note is not None:
        customer.note = note
    if status is not None:
        customer.status = status

    await db.flush()
    await db.refresh(customer)
    await _invalidate_customer_cache()
    return customer


async def toggle_customer_status(db: AsyncSession, customer_id: int) -> Customer:
    """切换客户状态"""
    customer = await db.get(Customer, customer_id)
    if not customer:
        raise ValueError("客户不存在")

    customer.status = not customer.status
    await db.flush()
    await db.refresh(customer)
    await _invalidate_customer_cache()
    return customer


async def delete_customer(db: AsyncSession, customer_id: int) -> None:
    """删除客户"""
    customer = await db.get(Customer, customer_id)
    if not customer:
        raise ValueError("客户不存在")

    has_orders = await db.execute(
        select(Order).where(Order.customer == customer.name, Order.is_deleted == False).limit(1)
    )
    has_stockins = await db.execute(
        select(StockIn).where(StockIn.customer == customer.name).limit(1)
    )
    has_stockouts = await db.execute(
        select(StockOut).where(StockOut.customer == customer.name).limit(1)
    )
    has_access_logs = await db.execute(
        select(CustomerAccessLog).where(CustomerAccessLog.customer_id == customer_id).limit(1)
    )
    has_purchase_orders = await db.execute(
        select(PurchaseOrder).where(PurchaseOrder.customer_id == customer_id).limit(1)
    )
    has_purchase_plans = await db.execute(
        select(PurchasePlan).where(PurchasePlan.customer_id == customer_id).limit(1)
    )

    if (has_orders.scalar_one_or_none() or has_stockins.scalar_one_or_none() or has_stockouts.scalar_one_or_none()
            or has_access_logs.scalar_one_or_none() or has_purchase_orders.scalar_one_or_none() or has_purchase_plans.scalar_one_or_none()):
        raise ValueError("该客户已有相关单据，无法删除！建议禁用该客户。")

    await db.delete(customer)
    await db.flush()
    await _invalidate_customer_cache()


async def _invalidate_customer_cache():
    """清除客户名称缓存"""
    try:
        from utils.redis_cache import redis_cache
        await redis_cache.delete(_ACTIVE_CUSTOMER_CACHE_KEY)
    except (OSError, ConnectionError, ValueError):
        logger.warning("客户缓存清除失败", exc_info=True)
