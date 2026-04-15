"""
生产计划页面路由

提供页面渲染功能，API逻辑已迁移至 FastAPI。
"""
from flask import Blueprint, render_template

production_summary_bp = Blueprint('production_summary', __name__, url_prefix='/production-summary')


@production_summary_bp.route('/')
def index():
    """生产计划管理页面（手工部/包装部/汇总报表）"""
    return render_template('production_summary.html')
