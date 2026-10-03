"""
订单抵扣备货服务

从 batch_service.py 提取，消除 order_service ↔ batch_service 循环依赖。
本模块为 order 领域与 stockin 领域的共享工具层，单向依赖 shared_models 和 order_utils。
"""
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fastapi_app.services.numbering import generate_stockout_number
from fastapi_app.services.order_utils import compute_order_status_from_db
from fastapi_app.shared.stock_concurrency import (
    get_product_for_update,
    update_stock_with_optimistic_lock,
)
from fastapi_app.shared_models import InventoryLog, Order, Product, StockIn, StockOut

logger = logging.getLogger(__name__)


async def process_order_deduction(
    db: AsyncSession,
    order: Order,
    product_id: int,
    order_quantity: int,
    deduct_stock: bool = True,
    custom_deduct_quantity: int | None = None,
    product: Product | None = None,
) -> tuple[int, list]:
    """
    处理订单抵扣备货的核心逻辑

    业务规则：
    - 一个订单只能抵扣一个备货（不允许拆分到多个备货）
    - 如果单个备货数量不足订单数量，则部分抵扣
    - 按FIFO原则选择最早的可用备货
    """
    deduction_details: list[dict] = []

    if not deduct_stock:
        return 0, deduction_details

    try:
        # ⚠️ 统一锁序 **Product → StockIn**：必须**无条件**先锁 Product，不能只靠调用方。
        # 调用方可能传入**未加锁**的 product —— `batch_import_core.import_orders_from_data`
        # 的 `_pre_load_product_map` 只做 `select(Product)`（无 FOR UPDATE）。若此处跳过
        # Product 锁，行锁会由后面的 `update_stock_with_optimistic_lock` 的 UPDATE 才取得，
        # 实际顺序变成 **StockIn→Product**，与 `stock_in_service`（Product→StockIn）反向
        # → 死锁环（2026-10-03 第三轮审计：上一轮只对齐了部分调用方，环被挪到了这条路径）。
        # 对已持锁的调用方（order_batch_create / staging/order / batch_import_service），
        # 重复加锁是同一事务内的 no-op。
        product = await get_product_for_update(db, product_id)

        # 查询该订单对应产品的所有备货，按时间正序排列（加锁防止并发抵扣超额）
        result = await db.execute(
            select(StockIn)
            .where(
                StockIn.product_id == product_id,
                StockIn.customer == order.customer
            )
            .options(selectinload(StockIn.stockin_stockouts))
            .order_by(StockIn.stockin_date.asc(), StockIn.id.asc())
            .with_for_update()
        )
        stockins = result.scalars().all()

        # 计算每个备货的可用数量
        stockin_available = None
        for stockin in stockins:
            deducted = sum(s.quantity - s.returned_quantity for s in stockin.stockin_stockouts) if stockin.stockin_stockouts else 0
            available = stockin.quantity - deducted
            if available > 0:
                stockin_available = (stockin, available)
                break

        if not stockin_available:
            logger.info(f'订单{order.order_no}无可用备货抵扣')
            order.status = await compute_order_status_from_db(db, order)
            return 0, deduction_details

        stockin, available = stockin_available

        # 计算要抵扣的数量
        if custom_deduct_quantity is not None and custom_deduct_quantity > 0:
            deduct_amount = min(custom_deduct_quantity, available)
        else:
            deduct_amount = min(order_quantity, available)

        if deduct_amount < order_quantity and deduct_amount < available:
            logger.warning(f'订单{order.order_no}备货不足：需求{order_quantity}，可用{available}')

        # 生成出货编号并创建抵扣记录
        stockout_no = await generate_stockout_number(db)

        stockout = StockOut(
            stockout_no=stockout_no,
            stockout_date=datetime.now(UTC),  # aware UTC：stockout_date 列为 timestamptz
            product_id=stockin.product_id,
            quantity=deduct_amount,
            customer=order.customer,
            order_id=order.id,
            stockin_id=stockin.id,
            note=f'[订单抵扣]{order.order_no}'
        )
        db.add(stockout)

        log = InventoryLog(
            product_id=stockin.product_id,
            change_type='订单抵扣',
            change_quantity=-deduct_amount,
            related_id=stockout_no,
            note=f'订单抵扣备货：{stockin.stockin_no}，订单号：{order.order_no}'
        )
        db.add(log)

        deduction_details.append({
            'stockin_id': stockin.id,
            'stockin_no': stockin.stockin_no,
            'deduct_amount': deduct_amount,
            'stockout_no': stockout_no,
            'remaining_in_stockin': available - deduct_amount
        })

        # 更新产品库存（统一走乐观锁写入口，WHERE version=旧值；不再直写 current_stock）
        # product 已在函数开头无条件加锁，这里不再需要补锁
        if product and deduct_amount > 0:
            await update_stock_with_optimistic_lock(db, product_id, -deduct_amount)

        # 更新订单状态（派生计算：根据实际备货/出货量推导状态）
        order.status = await compute_order_status_from_db(db, order)

        logger.info(f'订单抵扣处理完成：订单{order.order_no}，抵扣数量{deduct_amount}，状态{order.status}')
        return deduct_amount, deduction_details

    except SQLAlchemyError as e:
        logger.error(f'订单抵扣数据库错误：{e!s}', exc_info=True)
        raise
    except (ValueError, TypeError, ArithmeticError) as e:
        logger.error(f'订单抵扣处理错误：{e!s}', exc_info=True)
        raise
