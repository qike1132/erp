"""
Flask 服务层 - 库存业务逻辑（向后兼容门面）

核心逻辑已迁移至 fastapi_app.shared.stock_crud_service（框架无关版本）。
本文件提供兼容层，自动注入 Flask db.session，保持旧导入路径可用。
"""
import logging

from app import db
from fastapi_app.shared.stock_crud_service import (
    calculate_available_shipment_quantity as _shared_calc,
    create_stockin as _shared_create_stockin,
    update_stockin as _shared_update_stockin,
    delete_stockin as _shared_delete_stockin,
    create_stockout as _shared_create_stockout,
    update_stockout as _shared_update_stockout,
    delete_stockout as _shared_delete_stockout,
    get_inventory as _shared_get_inventory,
    generate_order_number_sync,
    generate_stockin_number_sync,
    generate_stockout_number_sync,
)

logger = logging.getLogger(__name__)


def calculate_available_shipment_quantity(product_id, customer, order_type=None, country=None):
    """兼容旧签名：自动注入 db.session"""
    return _shared_calc(db.session, product_id, customer, order_type=order_type, country=country)


def create_stockin(product_id, quantity, customer, stockin_date, note, stockin_no=None):
    """兼容旧签名：自动注入 db.session"""
    return _shared_create_stockin(db.session, product_id, quantity, customer,
                                  stockin_date, note, stockin_no=stockin_no)


def update_stockin(stockin, new_quantity, customer, stockin_date, note):
    """兼容旧签名：自动注入 db.session"""
    return _shared_update_stockin(db.session, stockin, new_quantity, customer,
                                  stockin_date, note)


def delete_stockin(stockin):
    """兼容旧签名：自动注入 db.session"""
    return _shared_delete_stockin(db.session, stockin)


def create_stockout(product_id, quantity, customer, stockout_date, note,
                    order_id=None, stockin_id=None, order_type='regular', country=None):
    """
    兼容旧签名：自动注入 db.session
    注意：旧版 create_stockout 签名包含 order_id/stockin_id，新版统一通过 FIFO 分配。
    当 stockin_id 不为 None 时（抵扣出库），直接创建单条记录。
    """
    if stockin_id is not None:
        # 抵扣出库：不走 FIFO 分配，直接创建单条
        from fastapi_app.shared_models import StockOut as SharedStockOut
        from fastapi_app.shared.stock_concurrency import get_product_for_update_sync
        from fastapi_app.shared.stock_crud_service import generate_stockout_number_sync

        product = get_product_for_update_sync(db.session, product_id)
        if product.current_stock < quantity:
            raise ValueError('库存不足！')

        stockout = SharedStockOut(
            stockout_no=generate_stockout_number_sync(db.session),
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
        product.current_stock -= quantity
        from fastapi_app.shared_models import InventoryLog as SharedLog
        log = SharedLog(
            product_id=product_id,
            change_type='出库',
            change_quantity=-quantity,
            related_id=str(stockout.id),
            note=f'出库ID：{stockout.id}'
        )
        db.session.add(log)
        return stockout
    else:
        # 独立出库：走 FIFO 分配
        return _shared_create_stockout(db.session, product_id, quantity, customer,
                                       stockout_date, note, order_type=order_type,
                                       country=country)


def update_stockout(stockout, new_quantity, customer, stockout_date, note):
    """兼容旧签名：自动注入 db.session"""
    return _shared_update_stockout(db.session, stockout, new_quantity, customer,
                                   stockout_date, note)


def delete_stockout(stockout):
    """兼容旧签名：自动注入 db.session"""
    return _shared_delete_stockout(db.session, stockout)


def get_inventory(search_customer='', search_product=''):
    """兼容旧签名：自动注入 db.session"""
    return _shared_get_inventory(db.session, search_customer, search_product)
