"""
产品管理业务逻辑服务

核心业务逻辑，异步 SQLAlchemy 实现。
"""
import logging
from collections.abc import Awaitable, Callable

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.cache import CacheDomain, cache_result
from fastapi_app.core.cache_invalidation import InvalidationStrategy, cache_mgr
from fastapi_app.core.cache_keys import PRODUCT_LIST_CACHE_PATTERN
from fastapi_app.core.redis_wrapper import safe_delete_pattern
from fastapi_app.core.sanitizer import escape_like
from fastapi_app.core.validators import validate_not_empty
from fastapi_app.services.bom_service import has_bom as product_has_bom  # noqa: F401
from fastapi_app.services.signed_urls import strip_upload_signature
from fastapi_app.shared.stock_concurrency import assert_stock_available, get_product_for_update
from fastapi_app.shared_models import InventoryLog, Order, OrderItem, Product, StockIn, StockOut

logger = logging.getLogger(__name__)


def _schedule_post_commit(db: AsyncSession, callback: Callable[[], Awaitable[None]]) -> None:
    """注册事务提交成功后执行的异步回调（商品列表缓存失效专用）。

    回调会在 db_transaction 成功 commit 后按注册顺序执行；事务回滚则不执行。
    采用 post-commit 时机是为了消除竞态：若在提交前失效，并发请求可能在提交前
    读到旧数据并回写缓存，而提交后不再失效，脏数据将留存至 TTL 到期。

    复制自 services/purchase_plan_common.py 的同名模式（避免跨域 import 耦合）。
    """
    callbacks = db.info.setdefault('post_commit_callbacks', [])
    callbacks.append(callback)


async def _invalidate_product_list_cache() -> None:
    """失效商品列表分页缓存（product:list:*）。

    商品写操作会改变列表首屏内容，必须失效；与域级失效是「广覆盖 + 竞态兜底」的分工，
    不是重复：
      · 域级失效（cache_mgr.invalidate 的 INVENTORY 域，映射见 core/cache.py 的
        _DOMAIN_PATTERN_MAP）可能在**提交前**触发，用于广覆盖各类改库存的写入口；
      · 本回调在**提交后**执行，保证提交完成后必定再清一次，从而清除并发读在提交前
        读到旧数据并回写缓存所产生的脏数据，消除竞态窗口。

    作为 post-commit 回调执行；自带异常兜底，缓存侧故障不得影响业务返回
    （db_transaction 对回调亦有一层兜底）。
    """
    try:
        await safe_delete_pattern(PRODUCT_LIST_CACHE_PATTERN, context="商品列表缓存")
    except Exception:  # broad-except: 缓存失效失败不得影响业务主流程
        logger.warning("商品列表缓存失效失败", exc_info=True)


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


class ProductHasRelatedRecordsError(ProductDeleteError):
    """产品仍被计数未覆盖的表引用（采购计划明细、外发工序预设等）。

    只能由删除时的外键违例暴露，用于把 IntegrityError 转成可读的业务拒绝。
    """
    def __init__(self, product_name: str):
        super().__init__(
            message=f"产品「{product_name}」仍被历史单据引用，无法删除",
            error_code="HAS_RELATED_RECORDS"
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
        result = await db.execute(  # batch-loop: 分页批量拉取(offset/limit 游标),非 N+1
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
        image=strip_upload_signature(image or ''),
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
    _schedule_post_commit(db, _invalidate_product_list_cache)
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
    - 初始库存变更时调整 current_stock 并记录 InventoryLog；负库存判定收口到统一入口
      assert_stock_available（策略开关见 ALLOW_NEGATIVE_STOCK），不再内联比较
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
        # 剥掉上传接口回传的限时签名 query：原样入库会让出站的 sign_upload_url
        # 走"已含 ?"的幂等分支不再重签 → 过期后图片 410 且无法自愈。
        product.image = strip_upload_signature(image)
    if factory is not None:
        product.factory = factory

    if initial_stock is not None and initial_stock != product.initial_stock:
        stock_change = initial_stock - product.initial_stock
        new_current_stock = product.current_stock + stock_change
        # P1-2b（t26-F-02 修复）：负库存判定收口到统一入口，不再内联比较。
        # 缺省（策略关闭）时仍抛 ValueError 且文案逐字不变；ALLOW_NEGATIVE_STOCK 为真值时
        # 与统一入口同样放行，管理员路径不再被无条件硬拒。
        assert_stock_available(product.current_stock, stock_change,
                               message=f'初始库存调整将导致当前库存为负数（当前库存：{product.current_stock}，调整量：{stock_change:+d}）')
        product.initial_stock = initial_stock
        # 写入侧安全性：:267 的 get_product_for_update 已对该行取 FOR UPDATE 行锁，
        # 判定与写入在同一事务内完成，不存在 TOCTOU 窗口；库侧另有
        # ck_product_current_stock_nonneg 作为最后一道防线。
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
    _schedule_post_commit(db, _invalidate_product_list_cache)
    logger.info(f'产品编辑成功：{product.name}')
    return product.to_dict()


async def delete_product(db: AsyncSession, product_id: int) -> None:
    """
    删除产品

    业务规则：
    - 有关联单据（订单/入库/出库）时拒绝删除
    - 库存流水**保留**：删除前先把产品标识快照进流水行，删除后 product_id 由
      DB 置空（外键 SET NULL，迁移 073），变动历史不随产品消失（R1）

    错误代码：
    - PRODUCT_NOT_FOUND: 产品不存在
    - HAS_RELATED_ORDERS: 有关联订单
    - HAS_RELATED_STOCK_INS: 有关联备货记录
    - HAS_RELATED_STOCK_OUTS: 有关联出货记录
    """
    product = await db.get(Product, product_id)
    if not product:
        raise ProductNotFoundError(product_id)

    # 单次往返完成 3 类关联计数（多 SKU 订单需同时检查 Order.product_id 与 OrderItem.product_id）。
    # 软删订单**不**因 Order.product_id 而计入：真实删除路径（order/commands.py 的
    # _purge_order_related_rows）已清掉该订单的 order_item，软删订单不再持有对 product
    # 的外键引用，故不阻塞删除（否则「订单已全删」的产品永远删不掉）。
    # 但 order_item 仍引用本产品的订单必须计入 —— 那是 FK NO ACTION 的真实阻塞源，
    # 也兜住历史遗留未清理明细的软删订单。
    order_subq = select(func.count(Order.id)).where(
        or_(
            and_(Order.is_deleted.isnot(True), Order.product_id == product_id),
            Order.id.in_(select(OrderItem.order_id).where(OrderItem.product_id == product_id))
        )
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

    # R1：不再删除库存流水。外键已改 ON DELETE SET NULL，但 SET NULL 只保住行、
    # 保不住「这是哪个产品」——故删除前把产品标识快照进该产品名下的存量流水，
    # 使历史（含未接快照的旧写点）在删除后仍可读。
    # 逐列 coalesce：已有快照（写入时带出的真实值）优先，缺哪列补哪列。
    # 条码**只在此处快照**：产品存在时 JOIN 就能取到，写路径无需冗余它，
    # 少一次热路径上的属性依赖（写路径只带 name）。
    await db.execute(
        update(InventoryLog)
        .where(InventoryLog.product_id == product_id)
        .values(
            product_name=func.coalesce(InventoryLog.product_name, product.name),
            product_barcode=func.coalesce(InventoryLog.product_barcode, product.barcode),
        )
    )

    product_name = product.name
    try:
        await db.delete(product)
        await db.flush()
    except IntegrityError as e:
        # 计数未覆盖的表（采购计划明细、外发工序预设等）在此以 FK 违例暴露，
        # 统一转成业务错误，避免端点返回 500。
        logger.warning('删除产品被外键阻塞：product_id=%s err=%s', product_id, e.orig)
        raise ProductHasRelatedRecordsError(product_name) from e
    await cache_mgr.invalidate(InvalidationStrategy.DOMAIN, CacheDomain.ORDER_AND_INVENTORY | CacheDomain.PRODUCT | CacheDomain.STOCKIN)
    _schedule_post_commit(db, _invalidate_product_list_cache)
    logger.info(f'产品删除成功：{product.name}')


async def get_product_by_id(db: AsyncSession, product_id: int) -> dict:
    """按 ID 获取单个产品详情。不存在时抛 ValueError（端点转 404）。"""
    product = await db.get(Product, product_id)
    if not product:
        raise ValueError('产品不存在')
    return product.to_dict()


async def search_products(db: AsyncSession, query: str, *, search_service=None) -> list[dict]:
    """搜索产品（按名称或条码模糊匹配，大小写不敏感）

    委托至 product_search_service 统一实现，保持原有返回格式。

    Args:
        search_service: 可注入的搜索服务实例（测试时可替换），
            默认 None 时使用模块级单例 product_search_service。
    """
    if search_service is None:
        from fastapi_app.services.product_search_service import product_search_service
        search_service = product_search_service
    return await search_service.search_async_with_cache(db, query, limit=20)


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
