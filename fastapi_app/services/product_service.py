"""
产品管理业务逻辑服务

从 Flask product.py 提取的核心业务逻辑，适配异步 SQLAlchemy。
"""
import logging
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from fastapi_app.shared_models import Product, InventoryLog

logger = logging.getLogger(__name__)


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
    product = await db.get(Product, product_id)
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
    """
    product = await db.get(Product, product_id)
    if not product:
        raise ValueError('产品不存在')

    # 检查关联单据（使用product上的backref）
    if product.orders or product.stockins or product.stockouts:
        raise ValueError('该产品已有相关单据，无法删除！')

    # 删除关联的库存日志
    for log in product.inventory_logs:
        await db.delete(log)

    await db.delete(product)
    await db.commit()
    logger.info(f'产品删除成功：{product.name}')


async def search_products(db: AsyncSession, query: str) -> list[dict]:
    """搜索产品（按名称或条码模糊匹配）"""
    result = await db.execute(
        select(Product).where(
            Product.name.contains(query) | Product.barcode.contains(query)
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
