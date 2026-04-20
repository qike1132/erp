"""
产品管理业务逻辑服务

从 Flask product.py 提取的核心业务逻辑，适配异步 SQLAlchemy。
"""
import logging
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import SQLAlchemyError

from fastapi_app.shared_models import Product, InventoryLog
from fastapi_app.shared.stock_concurrency import get_product_for_update
from fastapi_app.services import escape_like

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


async def get_products(db: AsyncSession) -> list[dict]:
    """获取所有产品列表"""
    result = await db.execute(
        select(Product).order_by(Product.create_time.desc())
    )
    products = result.scalars().all()
    return [p.to_dict() for p in products]


async def create_product(db: AsyncSession, name: str, barcode: Optional[str],
                         image: Optional[str], initial_stock: int,
                         price: Optional[float] = None) -> dict:
    """
    创建产品

    业务规则（与Flask一致）：
    - 产品名称不能为空
    - 产品名称唯一（不区分大小写）
    - 初始库存 > 0 时记录 InventoryLog
    """
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
        initial_stock=initial_stock,
        current_stock=initial_stock
    )
    db.add(product)
    await db.flush()

    if initial_stock > 0:
        log = InventoryLog(
            product_id=product.id,
            change_type='初始库存',
            change_quantity=initial_stock,
            related_id=str(product.id),
            note='初始库存设置'
        )
        db.add(log)

    await db.commit()
    await db.refresh(product)
    logger.info(f'产品添加成功：{name}，初始库存：{initial_stock}')
    return product.to_dict()


async def update_product(db: AsyncSession, product_id: int, name: Optional[str],
                         barcode: Optional[str], image: Optional[str],
                         initial_stock: Optional[int],
                         price: Optional[float] = None) -> dict:
    """
    更新产品

    业务规则（与Flask一致）：
    - 名称唯一性检查（排除自身）
    - 初始库存变更时调整 current_stock 并记录 InventoryLog
    """
    product = await get_product_for_update(db, product_id)
    if not product:
        raise ValueError('产品不存在')

    if name and name != product.name:
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

    if initial_stock is not None and initial_stock != product.initial_stock:
        stock_change = initial_stock - product.initial_stock
        product.initial_stock = initial_stock
        product.current_stock += stock_change

        log = InventoryLog(
            product_id=product.id,
            change_type='初始库存调整',
            change_quantity=stock_change,
            related_id=str(product.id),
            note='初始库存调整'
        )
        db.add(log)

    await db.commit()
    await db.refresh(product)
    logger.info(f'产品编辑成功：{product.name}')
    return product.to_dict()


async def delete_product(db: AsyncSession, product_id: int) -> None:
    """
    删除产品

    业务规则（与Flask一致）：
    - 有关联单据（订单/入库/出库）时拒绝删除
    - 删除时级联删除库存日志

    错误代码：
    - PRODUCT_NOT_FOUND: 产品不存在
    - HAS_RELATED_ORDERS: 有关联订单
    - HAS_RELATED_STOCK_INS: 有关联备货记录
    - HAS_RELATED_STOCK_OUTS: 有关联出货记录
    """
    result = await db.execute(
        select(Product)
        .options(
            selectinload(Product.orders),
            selectinload(Product.stockins),
            selectinload(Product.stockouts),
            selectinload(Product.inventory_logs)
        )
        .where(Product.id == product_id)
    )
    product = result.scalar_one_or_none()

    if not product:
        raise ProductNotFoundError(product_id)

    if product.orders:
        raise ProductHasRelatedOrdersError(product.name, len(product.orders))

    if product.stockins:
        raise ProductHasRelatedStockInsError(product.name, len(product.stockins))

    if product.stockouts:
        raise ProductHasRelatedStockOutsError(product.name, len(product.stockouts))

    for log in product.inventory_logs:
        await db.delete(log)

    await db.delete(product)
    await db.commit()
    logger.info(f'产品删除成功：{product.name}')


async def search_products(db: AsyncSession, query: str) -> list[dict]:
    """搜索产品（按名称或条码模糊匹配）"""
    result = await db.execute(
        select(Product).where(
            Product.name.like(f'%{escape_like(query)}%') | Product.barcode.like(f'%{escape_like(query)}%')
        )
    )
    products = result.scalars().all()
    return [{
        'id': p.id,
        'name': p.name,
        'barcode': p.barcode,
        'price': float(p.price) if p.price else 0,
        'current_stock': p.current_stock
    } for p in products]


async def get_product_stock(db: AsyncSession, product_id: int) -> dict:
    """获取产品可用库存"""
    product = await db.get(Product, product_id)
    if not product:
        raise ValueError('产品不存在')

    return {
        'product_id': product.id,
        'name': product.name,
        'current_stock': product.current_stock,
        'available_stock': product.current_stock,
    }
