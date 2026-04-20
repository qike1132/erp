"""
审批管理路由蓝图
API路由已迁移至 FastAPI: /api/v1/approvals/*
此文件仅保留页面渲染路由
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session
from app import db
from app.models import Order, User, ApprovalRequest
from functools import wraps
from sqlalchemy.orm import joinedload
from sqlalchemy import func
from app.services.shared import escape_like

approval_bp = Blueprint('approval', __name__, url_prefix='/approval')


def admin_required(f):
    """管理员权限检查装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'error': '请先登录', 'success': False}), 401
            flash('请先登录！', 'error')
            return redirect(url_for('main.login'))

        user = db.session.get(User, session['user_id'])
        if not user:
            if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'error': '用户不存在', 'success': False}), 401
            flash('用户不存在！', 'error')
            return redirect(url_for('main.login'))

        if not user.is_super:
            if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'error': '需要管理员权限', 'success': False}), 403
            flash('需要管理员权限！', 'error')
            return redirect(url_for('main.index'))

        return f(*args, **kwargs)
    return decorated_function


def get_current_user():
    """获取当前登录用户"""
    if 'user_id' not in session:
        return None
    return db.session.get(User, session['user_id'])


@approval_bp.route('/list')
@admin_required
def approval_list():
    """审批列表页面（支持搜索和分页）"""
    current_user = get_current_user()

    status_filter = request.args.get('status', 'pending')
    search = request.args.get('search', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    per_page = min(per_page, 100)

    query = ApprovalRequest.query.options(
        joinedload(ApprovalRequest.order),
        joinedload(ApprovalRequest.requester),
        joinedload(ApprovalRequest.approver)
    )

    if status_filter != 'all':
        query = query.filter(ApprovalRequest.status == status_filter)

    if search:
        query = query.join(Order, ApprovalRequest.order_id == Order.id, isouter=True)\
                     .join(User, ApprovalRequest.requester_id == User.id)\
                     .filter(
                         db.or_(
                             Order.order_no.like(f'%{escape_like(search)}%'),
                             User.username.like(f'%{escape_like(search)}%'),
                             ApprovalRequest.operation_type.like(f'%{escape_like(search)}%')
                         )
                     )

    pagination = query.order_by(ApprovalRequest.request_time.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    approvals = pagination.items

    stats = db.session.query(
        ApprovalRequest.status,
        func.count(ApprovalRequest.id)
    ).group_by(ApprovalRequest.status).all()

    stats_dict = dict(stats)
    pending_count = stats_dict.get('pending', 0)
    approved_count = stats_dict.get('approved', 0)
    rejected_count = stats_dict.get('rejected', 0)

    return render_template('approval_list.html',
                          approvals=approvals,
                          current_user=current_user,
                          status_filter=status_filter,
                          pending_count=pending_count,
                          approved_count=approved_count,
                          rejected_count=rejected_count,
                          pagination=pagination,
                          search=search)


@approval_bp.route('/detail/<int:id>')
@admin_required
def approval_detail(id):
    """审批详情页面"""
    current_user = get_current_user()
    approval_request = ApprovalRequest.query.get_or_404(id)

    return render_template('approval_detail.html',
                          approval=approval_request,
                          current_user=current_user)
