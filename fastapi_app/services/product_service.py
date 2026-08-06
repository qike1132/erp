"""
产品管理业务逻辑服务

核心业务逻辑，异步 SQLAlchemy 实现。
"""
import logging

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.cache import CacheDomain, cache_result
from fastapi_app.core.cache_invalidation import InvalidationStrategy, cache_mgr
from fastapi_app.core.sanitizer import escape_like
from fastapi_app.core.validators import validate_not_empty
from fastapi_app.shared.stock_concurrency import get_product_for_update
from fastapi_app.shared_models import InventoryLog, Order, OrderItem, Product, StockIn, StockOut
from fastapi_app.services.bom_service import has_bom as product_has_bom  # noqa: F401

logger = logging.getLogger(__name__)


class ProductDeleteError(Exception):
    """产品删除错误基类"""
    def __init__(self, message: str, error_code: str):
        self.message = message
        self.error_code = error_code
        super().__init__(self.message)


class ProductNotFoundError(ProductDeleteError):
    """产品不存在错误"""
    def __init__(self, product_id: int):
        super().__init__(
            message=f"产品不存在（ID: {product_id}）",
            error_code="PRODUCT_NOT_FOUND"
        )


class ProductHasRelatedOrdersError(ProductDeleteError):
    """产品有关联订单错误"""
    def __init__(self, product_name: str, order_count: int):
        super().__init__(
            message=f"产品「{product_name}」已关联 {order_count} 个订单，无法删除",
            error_code="HAS_RELATED_ORDERS"
        )


class ProductHasRelatedStockInsError(ProductDeleteError):
    """产品有关联入库单错误"""
    def __init__(self, product_name: str, stockin_count: int):
        super().__init__(
            message=f"产品「{product_name}」已关联 {stockin_count} 条备货记录，无法删除",
            error_code="HAS_RELATED_STOCK_INS"
        )


class ProductHasRelatedStockOutsError(ProductDeleteError):
    """产品有关联出库单错误"""
    def __init__(self, product_name: str, stockout_count: int):
        super().__init__(
            message=f"产品「{product_name}」已关联 {stockout_count} 条出货记录，无法删除",
            error_code="HAS_RELATED_STOCK_OUTS"
        )


@cache_result(key_prefix="products:all", ttl=60, local_ttl=15,
              key_builder=lambda **kwargs: f"limit{kwargs.get('limit', 5000)}")
async def get_products(db: AsyncSession, limit: int = 5000) -> list[dict]:
    """获取所有产品列表（内部使用，如搜索、映射构建等场景）

    Args:
        limit: 最大返回条数，防止全表扫描导致内存溢出
    """
    result = await db.execute(
        select(Product).order_by(Product.create_time.desc()).limit(limit)
    )
    products = result.scalars().all()
    return [p.to_dict() for p in products]


async def get_product_barcode_map(db: AsyncSession, limit: int | None = None, batch_size: int = 1000) -> dict[str, str]:
    """构建 {barcode: name} 映射，使用分页迭代避免全量加载到内存。

    替代 validate_staging 场景下的 get_products(db) 全量调用，
    仅 SELECT barcode 和 name 两列，跳过空条码。

    Args:
        db: 异步数据库会话。
        limit: 可选，限制总返回条数（None 表示不限制）。
        batch_size: 单批查询大小，默认 1000。

    Returns:
        dict[str, str]: {barcode: product_name} 映射，空条码被跳过。
    """
    result_map: dict[str, str] = {}
    offset = 0
    while True:
        batch_limit = batch_size
        if limit is not None:
            remaining = limit - len(result_map)
            if remaining <= 0:
                break
            batch_limit = min(batch_size, remaining)
        result = await db.execute(
            select(Product.barcode, Product.name)
            .where(Product.barcode.isnot(None), Product.barcode != '')
            .limit(batch_limit)
            .offset(offset)
        )
        rows = result.all()
        if not rows:
            break
        for barcode, name in rows:
            result_map[barcode] = name
        if len(rows) < batch_limit:
            break
        offset += batch_limit
    return result_map


async def get_products_page(db: AsyncSession, page: int = 1, per_page: int = 20, search: str = '') -> dict:
    """获取产品列表（分页+搜索），避免产品数过大时全量加载"""
    per_page = min(max(1, per_page), 200)
    query = select(Product)
    count_query = select(func.count(Product.id))
    if search:
        escaped = escape_like(search)
        search_filter = or_(Product.name.ilike(f'%{escaped}%', escape='\\'), Product.barcode.ilike(f'%{escaped}%', escape='\\'))
        query = query.where(search_filter)
        count_query = count_query.where(search_filter)
    total = (await db.execute(count_query)).scalar() or 0
    result = await db.execute(
        query.order_by(Product.create_time.desc())
        .offset((page - 1) * per_page).limit(per_page)
    )
    products = result.scalars().all()
    return {
        'items': [p.to_dict() for p in products],
        'total': total,
        'page': page,
        'per_page': per_page,
    }


async def create_product(db: AsyncSession, name: str, barcode: str | None,
                         image: str | None, initial_stock: int,
                         price: float | None = None,
                         factory: str | None = None) -> dict:
    """
    创建产品

    业务规则：
    - 产品名称不能为空
    - 产品名称唯一（不区分大小写）
    - 初始库存 >= 0
    - 初始库存 > 0 时记录 InventoryLog
    """
    validate_not_empty(name, "产品名称")
    if initial_stock < 0:
        raise ValueError('初始库存不能为负数')

    # 检查名称唯一性
    result = await db.execute(
        select(Product).where(func.lower(Product.name) == func.lower(name))
    )
    existing = result.scalar_one_or_none()
    if existing:
        raise ValueError(f'产品名称"{name}"已存在，每个产品名称必须是唯一的！')

    product = Product(
        name=name,
        barcode=barcode or '',
        price=price or 0,
        image=image or '',
        factory=factory or '',
        initial_stock=initial_stock,
        current_stock=initial_stock
    )
    db.add(product)
    try:
        await db.flush()
    except IntegrityError as e:
        # 并发场景下 SELECT 检查与 INSERT 之间可能存在竞态，
        # 由 DB 唯一约束兜底，转为友好的业务错误（db_transaction 会将 ValueError 转 400）
        if 'product_name_key' in str(e.orig).lower() or 'uq_product_name' in str(e.orig).lower():
            raise ValueError(f'产品名称"{name}"已存在，每个产品名称必须是唯一的！') from e
        raise

    if initial_stock > 0:
        log = InventoryLog(
            product_id=product.id,
            change_type='初始库存',
            change_quantity=initial_stock,
            related_id=str(product.id),
            note='初始库存设置'
        )
        db.add(log)

    await db.flush()
    await db.refresh(product)
    await cache_mgr.invalidate(InvalidationStrategy.DOMAIN, CacheDomain.ORDER_AND_INVENTORY | CacheDomain.PRODUCT | CacheDomain.STOCKIN)
    logger.info(f'产品添加成功：{name}，初始库存：{initial_stock}')
    return product.to_dict()


async def update_product(db: AsyncSession, product_id: int, name: str | None,
                         barcode: str | None, image: str | None,
                         initial_stock: int | None,
                         price: float | None = None,
                         factory: str | None = None) -> dict:
    """
    更新产品

    业务规则：
    - 名称唯一性检查（排除自身）
    - 初始库存变更时调整 current_stock 并记录 InventoryLog
    """
    product = await get_product_for_update(db, product_id)
    if not product:
        raise ValueError('产品不存在')

    if name and name.strip() != product.name:
        result = await db.execute(
            select(Product).where(
                func.lower(Product.name) == func.lower(name),
                Product.id != product_id
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            raise ValueError(f'产品名称"{name}"已存在，每个产品名称必须是唯一的！')
        product.name = name

    if barcode is not None:
        product.barcode = barcode
    if price is not None:
        product.price = price
    if image is not None:
        product.image = image
    if factory is not None:
        product.factory = factory

    if initial_stock is not None and initial_stock != product.initial_stock:
        stock_change = initial_stock - product.initial_stock
        new_current_stock = product.current_stock + stock_change
        if new_current_stock < 0:
            raise ValueError(f'初始库存调整将导致当前库存为负数（当前库存：{product.current_stock}，调整量：{stock_change:+d}）')
        product.initial_stock = initial_stock
        product.current_stock = new_current_stock

        log = InventoryLog(
            product_id=product.id,
            change_type='初始库存调整',
            change_quantity=stock_change,
            related_id=str(product.id),
            note='初始库存调整'
        )
        db.add(log)

    try:
        await db.flush()
    except IntegrityError as e:
        if 'product_name_key' in str(e.orig).lower() or 'uq_product_name' in str(e.orig).lower():
            raise ValueError(f'产品名称"{name or product.name}"已存在，每个产品名称必须是唯一的！') from e
        raise
    await db.refresh(product)
    await cache_mgr.invalidate(InvalidationStrategy.DOMAIN, CacheDomain.ORDER_AND_INVENTORY | CacheDomain.PRODUCT | CacheDomain.STOCKIN)
    logger.info(f'产品编辑成功：{product.name}')
    return product.to_dict()


async def delete_product(db: AsyncSession, product_id: int) -> None:
    """
    删除产品

    业务规则：
    - 有关联单据（订单/入库/出库）时拒绝删除
    - 删除时级联删除库存日志

    错误代码：
    - PRODUCT_NOT_FOUND: 产品不存在
    - HAS_RELATED_ORDERS: 有关联订单
    - HAS_RELATED_STOCK_INS: 有关联备货记录
    - HAS_RELATED_STOCK_OUTS: 有关联出货记录
    """
    product = await db.get(Product, product_id)
    if not product:
        raise ProductNotFoundError(product_id)

    # 单次往返完成 3 类关联计数（多 SKU 订单需同时检查 Order.product_id 与 OrderItem.product_id）
    order_subq = select(func.count(Order.id)).where(
        or_(
            Order.product_id == product_id,
            Order.id.in_(select(OrderItem.order_id).where(OrderItem.product_id == product_id))
        ),
        Order.is_deleted.isnot(True)
    ).scalar_subquery()
    stockin_subq = select(func.count(StockIn.id)).where(StockIn.product_id == product_id).scalar_subquery()
    stockout_subq = select(func.count(StockOut.id)).where(StockOut.product_id == product_id).scalar_subquery()

    order_count, stockin_count, stockout_count = (await db.execute(
        select(order_subq, stockin_subq, stockout_subq)
    )).one()
    order_count = order_count or 0
    stockin_count = stockin_count or 0
    stockout_count = stockout_count or 0

    if order_count > 0:
        raise ProductHasRelatedOrdersError(product.name, order_count)
    if stockin_count > 0:
        raise ProductHasRelatedStockInsError(product.name, stockin_count)
    if stockout_count > 0:
        raise ProductHasRelatedStockOutsError(product.name, stockout_count)

    # 删除库存日志（批量删除避免逐条加载）
    await db.execute(
        delete(InventoryLog).where(InventoryLog.product_id == product_id)
    )

    await db.delete(product)
    await db.flush()
    await cache_mgr.invalidate(InvalidationStrategy.DOMAIN, CacheDomain.ORDER_AND_INVENTORY | CacheDomain.PRODUCT | CacheDomain.STOCKIN)
    logger.info(f'产品删除成功：{product.name}')


async def get_product_by_id(db: AsyncSession, product_id: int) -> dict:
    """按 ID 获取单个产品详情。不存在时抛 ValueError（端点转 404）。"""
    product = await db.get(Product, product_id)
    if not product:
        raise ValueError('产品不存在')
    return product.to_dict()


async def search_products(db: AsyncSession, query: str) -> list[dict]:
    """搜索产品（按名称或条码模糊匹配，大小写不敏感）

    委托至 product_search_service 统一实现，保持原有返回格式。
    """
    from fastapi_app.services.product_search_service import product_search_service as _search_svc
    return await _search_svc.search_async_with_cache(db, query, limit=20)


async def get_product_stock(db: AsyncSession, product_id: int) -> dict:
    """获取产品可用库存（当前 available_stock = current_stock，后续可扩展扣减已分配量）"""
    product = await db.get(Product, product_id)
    if not product:
        raise ValueError('产品不存在')

    return {
        'product_id': product.id,
        'name': product.name,
        'current_stock': product.current_stock,
        'available_stock': product.current_stock,
    }
