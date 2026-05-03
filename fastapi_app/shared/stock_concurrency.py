"""
库存并发安全工具

提供悲观锁 + 乐观锁双重保障，确保 product.current_stock 在并发场景下不会出现数据不一致。
用法参照 Case 模型的 with_for_update() 模式。

本模块为跨框架共享模块，Flask 和 FastAPI 均可直接导入使用，不依赖任何 Web 框架。
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from fastapi_app.shared_models import Product

logger = logging.getLogger(__name__)

# 乐观锁冲突时的最大重试次数
MAX_RETRY = 3


class StockConcurrentError(Exception):
    """库存并发冲突异常"""
    pass


async def get_product_for_update(db: AsyncSession, product_id: int) -> Product:
    """
    获取产品并加行级悲观锁（SELECT ... FOR UPDATE）。

    在事务内使用，确保同一产品的库存不会被并发修改。
    用法：
        product = await get_product_for_update(db, product_id)
        product.current_stock += quantity
        await db.commit()
    """
    result = await db.execute(
        select(Product).where(Product.id == product_id).with_for_update()
    )
    product = result.scalar_one_or_none()
    if not product:
        raise ValueError(f'产品ID {product_id} 不存在')
    return product


def get_product_for_update_sync(db: Session, product_id: int) -> Product:
    """同步版本：获取产品并加行级悲观锁（供 Flask 路径使用）"""
    result = db.execute(
        select(Product).where(Product.id == product_id).with_for_update()
    )
    product = result.scalar_one_or_none()
    if not product:
        raise ValueError(f'产品ID {product_id} 不存在')
    return product


async def update_stock_with_optimistic_lock(
    db: AsyncSession,
    product_id: int,
    delta: int,
    retries: int = MAX_RETRY,
) -> Product:
    """
    使用乐观锁更新产品库存。

    1. 读取产品（含 version）
    2. 修改 current_stock
    3. 提交时 WHERE 条件包含 version，若 version 变化则影响行数为 0
    4. 失败时重试（最多 retries 次）

    Args:
        db: 异步数据库会话
        product_id: 产品ID
        delta: 库存变化量（正数为增加，负数为减少）
        retries: 最大重试次数

    Returns:
        更新后的 Product 对象

    Raises:
        StockConcurrentError: 重试耗尽仍冲突
        ValueError: 库存不足
    """
    for attempt in range(retries):
        async with db.begin_nested():
            # 1. 读取当前产品和版本
            product = await db.get(Product, product_id)
            if not product:
                raise ValueError(f'产品ID {product_id} 不存在')

            old_version = product.version
            new_stock = product.current_stock + delta

            # 库存不足检查
            if new_stock < 0:
                raise ValueError(f'库存不足！当前库存: {product.current_stock}，需要: {abs(delta)}')

            # 2. 使用乐观锁更新：WHERE version = old_version
            from sqlalchemy import update
            stmt = (
                update(Product)
                .where(Product.id == product_id, Product.version == old_version)
                .values(current_stock=new_stock, version=old_version + 1)
            )
            result = await db.execute(stmt)

            if result.rowcount == 1:
                # 更新成功，刷新对象
                await db.refresh(product)
                logger.info(f'库存更新成功: 产品ID={product_id}, delta={delta}, '
                            f'new_stock={new_stock}, version={old_version}->{old_version + 1}')
                return product

        # 版本冲突，savepoint 已自动回滚，保留事务中其他有效修改
        logger.warning(f'库存乐观锁冲突: 产品ID={product_id}, 第{attempt + 1}次重试')

    raise StockConcurrentError(
        f'库存并发冲突，重试{retries}次后仍失败: 产品ID={product_id}'
    )
