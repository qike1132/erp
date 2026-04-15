"""
排产计划页面路由

提供页面渲染功能，API逻辑已迁移至 FastAPI。
"""
from flask import Blueprint, render_template
from app.models import Customer

production_plan_bp = Blueprint('production_plan', __name__, url_prefix='/production-plan')


@production_plan_bp.route('/list')
def plan_list():
    """排产计划管理页面"""
    customers = Customer.query.filter_by(status=True).order_by(Customer.name).all()
    return render_template('production_plan.html', customers=customers)
