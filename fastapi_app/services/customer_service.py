"""客户管理服务层"""
import logging

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.cache_invalidation import InvalidationStrategy, cache_mgr
from fastapi_app.shared_models import (
    CaseMovement,
    Customer,
    CustomerAccessLog,
    Order,
    PackagingRecord,
    ProductCustomer,
    ProductionPlan,
    PurchaseOrder,
    PurchasePlan,
    StockIn,
    StockOut,
)

logger = logging.getLogger(__name__)

_ACTIVE_CUSTOMER_CACHE_KEY = "active_customer_names"
_ACTIVE_CUSTOMER_CACHE_TTL = 300


async def get_customers(db: AsyncSession, status: str | None = None, page: int = 1, per_page: int = 50, search: str = '') -> dict:
    """获取客户列表（支持分页和搜索）"""
    query = select(Customer)
    count_query = select(func.count(Customer.id))
    from fastapi_app.shared.customer_status import apply_customer_status_filter
    query, count_query = apply_customer_status_filter(query, count_query, status)
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


async def search_customers(db: AsyncSession, query_str: str, *, search_service=None) -> list[Customer]:
    """搜索客户（按名称/联系人/电话模糊匹配，仅返回启用状态）

    委托至 customer_search_service 统一实现，再根据 ID 回查 ORM 对象
    以保持原有返回类型（list[Customer]）的向后兼容。

    Args:
        search_service: 可注入的搜索服务实例（测试时可替换），
            默认 None 时使用模块级单例 customer_search_service。
    """
    if search_service is None:
        from fastapi_app.services.customer_search_service import customer_search_service
        search_service = customer_search_service

    results = await search_service.search_active_customers(db, query_str, limit=20)

    if not results:
        return []

    customer_ids = [r["id"] for r in results]
    result = await db.execute(
        select(Customer).where(Customer.id.in_(customer_ids))
    )
    return list(result.scalars().all())


async def get_active_customer_names(db: AsyncSession) -> list[dict]:
    """获取所有启用客户名称列表（带Redis缓存5分钟）"""
    from fastapi_app.core.redis_wrapper import safe_get, safe_set
    cached = await safe_get(_ACTIVE_CUSTOMER_CACHE_KEY, context='客户名称缓存')
    if cached:
        return cached

    result = await db.execute(
        # limit(2000)：下拉全量名单的内存/响应上界（批次1 防护，超出属异常数据量）
        select(Customer).where(Customer.status).order_by(Customer.name).limit(2000)
    )
    data = [{'id': c.id, 'name': c.name} for c in result.scalars().all()]

    await safe_set(_ACTIVE_CUSTOMER_CACHE_KEY, data, timeout=_ACTIVE_CUSTOMER_CACHE_TTL, context='客户名称缓存')

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

    # 单次查询统计所有关联数据（计数明细而非仅 EXISTS），覆盖所有以客户名/客户ID 引用的表：
    # - 名称字符串引用：Order/StockIn/StockOut/PackagingRecord/ProductionPlan/CaseMovement
    # - customer_id 外键引用（优先 ID 检查）：PurchaseOrder/PurchasePlan/CustomerAccessLog，
    #   同时兜底匹配冗余的 customer_name 字段（历史数据 customer_id 可能为 NULL）
    checks = await db.execute(
        select(
            # ⚠️ 必须写 `isnot(True)`，不能写 `not Order.is_deleted`：
            #    `not <SQLAlchemy 列>` 走的是 Python 的 `__bool__`，求值为**普通
            #    布尔 False**（不是 SQL 表达式），导致整个 WHERE 恒假
            #    （生成 `WHERE false`），count 永远为 0 → 本守卫**永不触发**。
            #    列可空，故用 isnot(True)（NULL 也视为未删除），与项目既有惯例一致。
            select(func.count()).where(Order.customer == customer.name, Order.is_deleted.isnot(True)).scalar_subquery().label('orders'),
            select(func.count()).where(StockIn.customer == customer.name).scalar_subquery().label('stockins'),
            select(func.count()).where(StockOut.customer == customer.name).scalar_subquery().label('stockouts'),
            select(func.count()).where(
                or_(CustomerAccessLog.customer_id == customer_id, CustomerAccessLog.customer_name == customer.name)
            ).scalar_subquery().label('access_logs'),
            select(func.count()).where(
                or_(PurchaseOrder.customer_id == customer_id, PurchaseOrder.customer_name == customer.name)
            ).scalar_subquery().label('purchase_orders'),
            select(func.count()).where(
                or_(PurchasePlan.customer_id == customer_id, PurchasePlan.customer_name == customer.name)
            ).scalar_subquery().label('purchase_plans'),
            select(func.count()).where(PackagingRecord.customer == customer.name).scalar_subquery().label('packaging_records'),
            select(func.count()).where(ProductionPlan.customer_name == customer.name).scalar_subquery().label('production_plans'),
            select(func.count()).where(CaseMovement.customer == customer.name, CaseMovement.direction == 'in').scalar_subquery().label('case_stockins'),
            select(func.count()).where(CaseMovement.customer == customer.name, CaseMovement.direction == 'out').scalar_subquery().label('case_stockouts'),
            # product_customer 随 FK CASCADE 静默清除，而可见性口径是
            # 「未挂客户的 SKU 对所有客户可见」——漏数会瞬间放大 SKU 可见范围且无提示。
            select(func.count()).where(ProductCustomer.customer_id == customer_id).scalar_subquery().label('product_customers'),
        )
    )
    row = checks.one()
    related_counts = {
        '订单': row.orders,
        '备货记录': row.stockins,
        '出货记录': row.stockouts,
        '客户访问日志': row.access_logs,
        '采购订单': row.purchase_orders,
        '采购计划': row.purchase_plans,
        '包装记录': row.packaging_records,
        '生产计划': row.production_plans,
        '皮套入仓': row.case_stockins,
        '皮套出仓': row.case_stockouts,
        'SKU 客户归属': row.product_customers,
    }
    related = {label: cnt for label, cnt in related_counts.items() if cnt}
    if related:
        detail = '、'.join(f'{label} {cnt} 条' for label, cnt in related.items())
        raise ValueError(f"该客户已有相关单据，无法删除！建议禁用该客户。关联明细：{detail}")

    await db.delete(customer)
    await db.flush()
    await _invalidate_customer_cache()


async def _invalidate_customer_cache():
    """清除客户名称缓存"""
    await cache_mgr.invalidate(InvalidationStrategy.KEYS, [_ACTIVE_CUSTOMER_CACHE_KEY])
