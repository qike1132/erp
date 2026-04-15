"""
Flask 服务层 - 库存业务逻辑

从 app/routes/stock.py 提取的可复用业务函数。
所有函数接收 db.session 作为参数，不依赖 Flask request/session。
"""
import logging
from datetime import datetime

from app import db
from app.models import Product, StockIn, StockOut, InventoryLog, Order
from fastapi_app.services.stock_concurrency import get_product_for_update_sync

logger = logging.getLogger(__name__)


def calculate_available_shipment_quantity(product_id, customer):
    """
    计算指定客户和产品的可出货量

    业务规则：
    1. 出货量严格受限于订单量
    2. 备货量只能通过订单抵扣使用，不能直接出货
    3. 可出货量 = 订单总量 - 已出货量（非抵扣出货）

    Args:
        product_id: 产品ID
        customer: 客户名称

    Returns:
        dict: { order_quantity, shipped_quantity, available_quantity, orders }
    """
    orders = Order.query.filter_by(
        product_id=product_id,
        customer=customer
    ).order_by(Order.order_date.asc()).all()

    total_order_quantity = 0
    order_details = []

    for order in orders:
        total_order_quantity += order.quantity

        non_deduction_shipped = db.session.query(
            db.func.sum(StockOut.quantity)
        ).filter(
            StockOut.order_id == order.id,
            StockOut.stockin_id.is_(None)
        ).scalar() or 0

        order_details.append({
            'order_id': order.id,
            'order_no': order.order_no,
            'quantity': order.quantity,
            'shipped': non_deduction_shipped,
            'available': order.quantity - non_deduction_shipped
        })

    total_shipped = db.session.query(
        db.func.sum(StockOut.quantity)
    ).join(Order, StockOut.order_id == Order.id).filter(
        Order.product_id == product_id,
        Order.customer == customer,
        StockOut.stockin_id.is_(None)
    ).scalar() or 0

    available_quantity = max(0, total_order_quantity - total_shipped)

    return {
        'order_quantity': total_order_quantity,
        'shipped_quantity': total_shipped,
        'available_quantity': available_quantity,
        'orders': order_details
    }


def create_stockin(product_id, quantity, customer, stockin_date, note, stockin_no):
    """创建入库记录，同时更新库存和写入日志"""
    stockin = StockIn(
        stockin_no=stockin_no,
        product_id=product_id,
        quantity=quantity,
        customer=customer,
        stockin_date=stockin_date,
        note=note
    )
    db.session.add(stockin)
    db.session.flush()

    product = get_product_for_update_sync(db.session, product_id)
    product.current_stock += quantity

    log = InventoryLog(
        product_id=product_id,
        change_type='入库',
        change_quantity=quantity,
        related_id=str(stockin.id),
        note=f'入库ID：{stockin.id}'
    )
    db.session.add(log)
    return stockin


def update_stockin(stockin, new_quantity, customer, stockin_date, note):
    """更新入库记录，调整库存差异"""
    old_quantity = stockin.quantity
    stockin.quantity = new_quantity
    stockin.customer = customer
    stockin.stockin_date = stockin_date
    stockin.note = note

    if new_quantity != old_quantity:
        product = get_product_for_update_sync(db.session, stockin.product_id)
        product.current_stock += (new_quantity - old_quantity)
        log = InventoryLog(
            product_id=stockin.product_id,
            change_type='入库修改',
            change_quantity=new_quantity - old_quantity,
            related_id=str(stockin.id),
            note=f'入库修改ID：{stockin.id}'
        )
        db.session.add(log)
    return stockin


def delete_stockin(stockin):
    """删除入库记录，回退库存。如果有关联出库则拒绝删除。"""
    if stockin.stockin_stockouts:
        raise ValueError('该入库记录已有出库关联，无法删除')

    product = get_product_for_update_sync(db.session, stockin.product_id)
    product.current_stock -= stockin.quantity

    log = InventoryLog(
        product_id=stockin.product_id,
        change_type='入库删除',
        change_quantity=-stockin.quantity,
        related_id=str(stockin.id),
        note=f'入库删除ID：{stockin.id}'
    )
    db.session.add(log)
    db.session.delete(stockin)


def create_stockout(product_id, quantity, customer, stockout_date, note, stockout_no,
                    order_id=None, stockin_id=None):
    """创建出库记录，扣减库存和写入日志"""
    stockout = StockOut(
        stockout_no=stockout_no,
        product_id=product_id,
        quantity=quantity,
        customer=customer,
        stockout_date=stockout_date,
        note=note,
        order_id=order_id,
        stockin_id=stockin_id
    )
    db.session.add(stockout)
    db.session.flush()

    product = get_product_for_update_sync(db.session, product_id)
    product.current_stock -= quantity

    log = InventoryLog(
        product_id=product_id,
        change_type='出库',
        change_quantity=-quantity,
        related_id=str(stockout.id),
        note=f'出库ID：{stockout.id}'
    )
    db.session.add(log)
    return stockout


def update_stockout(stockout, new_quantity, customer, stockout_date, note):
    """更新出库记录，调整库存差异"""
    old_quantity = stockout.quantity
    stockout.quantity = new_quantity
    stockout.customer = customer
    stockout.stockout_date = stockout_date
    stockout.note = note

    if new_quantity != old_quantity:
        product = get_product_for_update_sync(db.session, stockout.product_id)
        product.current_stock -= (new_quantity - old_quantity)
        log = InventoryLog(
            product_id=stockout.product_id,
            change_type='出库修改',
            change_quantity=-(new_quantity - old_quantity),
            related_id=str(stockout.id),
            note=f'出库修改ID：{stockout.id}'
        )
        db.session.add(log)
    return stockout


def delete_stockout(stockout):
    """删除出库记录，回退库存。如果是抵扣出库则拒绝删除。"""
    if stockout.stockin_id is not None:
        raise ValueError('抵扣出库记录无法单独删除')

    product = get_product_for_update_sync(db.session, stockout.product_id)
    product.current_stock += stockout.quantity

    log = InventoryLog(
        product_id=stockout.product_id,
        change_type='出库删除',
        change_quantity=stockout.quantity,
        related_id=str(stockout.id),
        note=f'出库删除ID：{stockout.id}'
    )
    db.session.add(log)
    db.session.delete(stockout)
