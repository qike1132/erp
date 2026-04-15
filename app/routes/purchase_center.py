"""
采购中心路由蓝图 - 用料计算与采购订单管理整合模块
API路由已迁移至 FastAPI: /api/v1/purchase-center/api/*
此文件仅保留页面渲染路由
"""
from flask import Blueprint, render_template
from app.utils.permission_decorators import api_permission_required

purchase_center_bp = Blueprint('purchase_center', __name__, url_prefix='/purchase-center')


@purchase_center_bp.route('/')
@api_permission_required('product_manage')
def index():
    return render_template('purchase_center.html')
