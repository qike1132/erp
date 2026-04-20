"""
客户订单路由蓝图
合并原"订单管理"和"备货管理"为统一的Tab页面
"""
from flask import Blueprint, render_template, request, jsonify
from app import db
from app.models import Order, Product, StockIn, Customer
from app.utils.permission_decorators import api_permission_required, page_permission_required
from fastapi_app.shared.stock_crud_service import generate_stockin_number_sync
from datetime import datetime
from sqlalchemy.orm import joinedload, selectinload, load_only
from sqlalchemy import distinct
import json
import logging

logger = logging.getLogger(__name__)

customer_order_bp = Blueprint('customer_order', __name__, url_prefix='/customer-order')


@customer_order_bp.route('/')
@page_permission_required('order_manage')
def index():
    """客户订单页面 - 包含订单管理和备货管理两个Tab"""

    # 页面渲染只提供基础数据（客户列表、国家列表），列表数据由 AJAX 加载
    customers = Customer.query.filter_by(status=True).order_by(Customer.name).limit(2000).all()
    preview_stockin_no = generate_stockin_number_sync(db.session)
    current_date = datetime.now().strftime('%Y-%m-%d')

    existing_countries = [row[0] for row in db.session.query(distinct(Order.country)).filter(Order.country.isnot(None), Order.country != '').all()]

    return render_template(
        'customer_order.html',
        # 初始不注入大数据，由 AJAX 分页加载
        orders=[],
        orders_json='[]',
        stockins=[],
        stockins_json='[]',
        preview_stockin_no=preview_stockin_no,
        current_date=current_date,
        customers=customers,
        countries=existing_countries,
        datetime=datetime
    )


# ==================== AJAX 分页 API ====================

from app import csrf

customer_order_api_bp = Blueprint('customer_order_api', __name__, url_prefix='/customer-order/api')
csrf.exempt(customer_order_api_bp)


@customer_order_api_bp.route('/orders')
@api_permission_required('order_manage')
def api_orders():
    """客户订单页 - 订单列表分页 API"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    query = Order.query.options(
        joinedload(Order.product).load_only(
            Product.id, Product.name, Product.barcode, Product.image
        ),
        selectinload(Order.order_stockouts),
        joinedload(Order.locked_by)
    ).order_by(Order.order_date.desc())

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    result = []
    for o in pagination.items:
        result.append({
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
            'order_type': getattr(o, 'order_type', 'regular') or 'regular',
            'country': getattr(o, 'country', '') or '',
            'is_locked': o.is_locked,
            'locked_by_name': o.locked_by.username if o.locked_by else None
        })

    return jsonify({
        'items': result,
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page
    })


@customer_order_api_bp.route('/stockins')
@api_permission_required('order_manage')
def api_stockins():
    """客户订单页 - 备货列表分页 API"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    query = StockIn.query.options(
        joinedload(StockIn.product).load_only(
            Product.id, Product.name, Product.barcode, Product.image
        ),
        selectinload(StockIn.stockin_stockouts)
    ).order_by(StockIn.stockin_date.desc())

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    result = []
    for s in pagination.items:
        result.append({
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
        })

    return jsonify({
        'items': result,
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page
    })
