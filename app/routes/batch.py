"""
批量导入工具模块
路由已迁移至 FastAPI: /api/v1/batch/*
此文件仅保留共享工具函数，供其他Flask路由调用
"""
from flask import Blueprint
from app import db
from app.models import Product, StockIn, StockOut, InventoryLog
from datetime import datetime
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import SQLAlchemyError
from utils.number_generator import generate_stockout_number
import logging
from fastapi_app.shared.stock_concurrency import get_product_for_update_sync

logger = logging.getLogger(__name__)

batch_bp = Blueprint('batch', __name__)


def process_order_deduction(order, product_id, order_quantity, deduct_stock=True, custom_deduct_quantity=None, product=None):
    """
    处理订单抵扣备货的核心逻辑

    业务规则：
    - 一个订单只能抵扣一个备货（不允许拆分到多个备货）
    - 如果单个备货数量不足订单数量，则部分抵扣或提示库存不足
    - 按FIFO原则选择最早的可用备货

    Args:
        order: 订单对象
        product_id: 产品ID
        order_quantity: 订单数量
        deduct_stock: 是否执行抵扣
        custom_deduct_quantity: 自定义抵扣数量（可选）
        product: 产品对象（可选，用于更新库存）

    Returns:
        tuple: (total_deducted, deduction_details)
            - total_deducted: 实际抵扣数量
            - deduction_details: 抵扣详情列表
    """
    deduction_details = []

    if not deduct_stock:
        return 0, deduction_details

    try:
        stockins = StockIn.query.filter_by(
            product_id=product_id,
            customer=order.customer
        ).options(
            selectinload(StockIn.stockin_stockouts)
        ).order_by(
            StockIn.stockin_date.asc(),
            StockIn.id.asc()
        ).all()

        stockin_available = None
        for stockin in stockins:
            deducted = sum(s.quantity for s in stockin.stockin_stockouts) if stockin.stockin_stockouts else 0
            available = stockin.quantity - deducted

            if available > 0:
                stockin_available = (stockin, available)
                break

        if not stockin_available:
            logger.info(f'订单{order.order_no}无可用备货抵扣')
            order.status = '待备货'
            return 0, deduction_details

        stockin, available = stockin_available

        if custom_deduct_quantity is not None and custom_deduct_quantity > 0:
            deduct_amount = min(custom_deduct_quantity, available)
        else:
            deduct_amount = min(order_quantity, available)

        if deduct_amount < order_quantity and deduct_amount < available:
            logger.warning(f'订单{order.order_no}备货不足：订单需求{order_quantity}，实际可用{available}')

        stockout_no = generate_stockout_number(db, StockOut)

        stockout = StockOut(
            stockout_no=stockout_no,
            stockout_date=datetime.now(),
            product_id=stockin.product_id,
            quantity=deduct_amount,
            customer=order.customer,
            order_id=order.id,
            stockin_id=stockin.id,
            note=f'[订单抵扣]{order.order_no}'
        )
        db.session.add(stockout)

        log = InventoryLog(
            product_id=stockin.product_id,
            change_type='订单抵扣',
            change_quantity=-deduct_amount,
            related_id=stockout_no,
            note=f'订单抵扣备货：{stockin.stockin_no}，订单号：{order.order_no}'
        )
        db.session.add(log)

        deduction_details.append({
            'stockin_id': stockin.id,
            'stockin_no': stockin.stockin_no,
            'deduct_amount': deduct_amount,
            'stockout_no': stockout_no,
            'remaining_in_stockin': available - deduct_amount
        })

        if product is None:
            product = get_product_for_update_sync(db.session, product_id)
        if product and deduct_amount > 0:
            product.current_stock -= deduct_amount

        if deduct_amount >= order_quantity:
            order.status = '已备货'
        elif deduct_amount > 0:
            order.status = '部分备货'
        else:
            order.status = '待备货'

        logger.info(f'订单抵扣处理完成：订单{order.order_no}，抵扣数量{deduct_amount}，从备货{stockin.stockin_no}')
        return deduct_amount, deduction_details

    except SQLAlchemyError as e:
        logger.error(f'订单抵扣数据库错误：{str(e)}', exc_info=True)
        raise
    except Exception as e:
        logger.error(f'订单抵扣处理错误：{str(e)}', exc_info=True)
        raise


def get_deduction_preview(order, product_id, order_quantity):
    """
    获取订单抵扣预览（不实际执行抵扣）

    Args:
        order: 订单对象
        product_id: 产品ID
        order_quantity: 订单数量

    Returns:
        dict: 预览信息
    """
    stockins = StockIn.query.filter_by(
        product_id=product_id,
        customer=order.customer
    ).options(
        selectinload(StockIn.stockin_stockouts)
    ).order_by(
        StockIn.stockin_date.asc(),
        StockIn.id.asc()
    ).all()

    total_available = 0
    preview_items = []

    for stockin in stockins:
        deducted = sum(s.quantity for s in stockin.stockin_stockouts) if stockin.stockin_stockouts else 0
        available = stockin.quantity - deducted

        if available > 0:
            preview_items.append({
                'stockin_id': stockin.id,
                'stockin_no': stockin.stockin_no,
                'stockin_date': stockin.stockin_date.strftime('%Y-%m-%d') if stockin.stockin_date else '',
                'total_quantity': stockin.quantity,
                'deducted': deducted,
                'available': available
            })
            total_available += available

    can_fully_deduct = total_available >= order_quantity

    return {
        'order_no': order.order_no,
        'order_quantity': order_quantity,
        'total_available': total_available,
        'can_fully_deduct': can_fully_deduct,
        'shortage': max(0, order_quantity - total_available),
        'preview_items': preview_items
    }
