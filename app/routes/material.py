"""
物料用量计算与采购订单生成模块路由蓝图
API路由已迁移至 FastAPI: /api/v1/purchase-center/api/*
此文件仅保留页面渲染路由
"""
from flask import Blueprint, render_template
from app.utils.permission_decorators import api_permission_required

material_bp = Blueprint('material', __name__, url_prefix='/material')


@material_bp.route('/calculator')
@api_permission_required('product_manage')
def calculator():
    """物料用量计算页面"""
    return render_template('material_calculator.html')


@material_bp.route('/orders')
@api_permission_required('product_manage')
def orders_list():
    """采购订单列表页面"""
    return render_template('purchase_orders.html')


@material_bp.route('/orders/<int:order_id>')
@api_permission_required('product_manage')
def order_detail(order_id):
    """采购订单详情页面"""
    return render_template('purchase_order_detail.html')
