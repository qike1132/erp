"""
客户订单路由蓝图
合并原"订单管理"和"备货管理"为统一的Tab页面
"""
from flask import Blueprint, render_template
from app import db
from app.models import Order, Product, StockIn, Customer
from app.utils.permission_decorators import page_permission_required
from utils.number_generator import generate_stockin_number
from datetime import datetime
from sqlalchemy.orm import joinedload, selectinload, load_only
import json
import logging

logger = logging.getLogger(__name__)

customer_order_bp = Blueprint('customer_order', __name__, url_prefix='/customer-order')


@customer_order_bp.route('/')
@page_permission_required('order_manage')
def index():
    """客户订单页面 - 包含订单管理和备货管理两个Tab"""

    # ========== 订单管理数据 ==========
    orders = Order.query.options(
        joinedload(Order.product).load_only(
            Product.id, Product.name, Product.barcode, Product.image
        ),
        selectinload(Order.order_stockouts),
        joinedload(Order.locked_by)
    ).order_by(Order.order_date.desc()).all()

    customers = Customer.query.filter_by(status=True).order_by(Customer.name).all()

    orders_json = json.dumps([{
        'id': o.id,
        'order_no': o.order_no,
        'customer': o.customer,
        'order_date': o.order_date.strftime('%Y-%m-%d %H:%M') if o.order_date else '',
        'product': {
            'id': o.product.id,
            'name': o.product.name,
            'barcode': o.product.barcode or '',
            'image': o.product.image or ''
        },
        'quantity': o.quantity,
        'deduct_quantity': sum(so.quantity for so in o.order_stockouts) if o.order_stockouts else 0,
        'status': o.status,
        'note': o.note or '',
        'is_locked': o.is_locked,
        'locked_by_name': o.locked_by.username if o.locked_by else None
    } for o in orders])

    # ========== 备货管理数据 ==========
    stockins = StockIn.query.options(
        joinedload(StockIn.product).load_only(
            Product.id, Product.name, Product.barcode, Product.image
        ),
        selectinload(StockIn.stockin_stockouts)
    ).order_by(StockIn.stockin_date.desc()).all()

    stockins_json = json.dumps([{
        'id': s.id,
        'stockin_no': s.stockin_no,
        'stockin_date': s.stockin_date.strftime('%Y-%m-%d') if s.stockin_date else '',
        'customer': s.customer,
        'product': {
            'id': s.product.id,
            'name': s.product.name,
            'barcode': s.product.barcode or '',
            'image': s.product.image or ''
        },
        'quantity': s.quantity,
        'deducted': sum(so.quantity for so in s.stockin_stockouts) if s.stockin_stockouts else 0,
        'note': s.note or ''
    } for s in stockins])

    preview_stockin_no = generate_stockin_number(db, StockIn)
    current_date = datetime.now().strftime('%Y-%m-%d')

    return render_template(
        'customer_order.html',
        # 订单管理数据
        orders=orders,
        orders_json=orders_json,
        # 备货管理数据
        stockins=stockins,
        stockins_json=stockins_json,
        preview_stockin_no=preview_stockin_no,
        current_date=current_date,
        # 共享数据
        customers=customers,
        datetime=datetime
    )
