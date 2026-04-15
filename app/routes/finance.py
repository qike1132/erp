"""
财务统计路由蓝图
API路由由 FastAPI 提供:
  - /api/v1/finance/customer-summary
  - /api/v1/finance/daily-amount
  - /api/v1/finance/daily-amount-chart
此文件仅保留页面渲染路由
"""
from flask import Blueprint, render_template, session
from functools import wraps
import logging

logger = logging.getLogger(__name__)

finance_bp = Blueprint('finance', __name__, url_prefix='/finance')


def finance_permission_required(permission_code):
    """财务权限验证装饰器"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            from flask import flash, redirect, url_for
            from app import db
            if not session.get('user_id'):
                flash('请先登录', 'error')
                return redirect(url_for('main.login'))
            from app.models import User
            user = db.session.get(User, session['user_id'])
            if not user:
                session.clear()
                flash('用户不存在', 'error')
                return redirect(url_for('main.login'))
            if user.is_super:
                return f(*args, **kwargs)
            has_permission = False
            for p in user.permissions:
                if p.code == permission_code:
                    has_permission = True
                    break
            if not has_permission:
                flash('无权限访问该页面', 'error')
                return redirect(url_for('main.index'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


@finance_bp.route('/statistics')
@finance_permission_required('finance_view')
def statistics():
    """财务统计页面"""
    return render_template('finance.html')
