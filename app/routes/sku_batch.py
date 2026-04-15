"""
SKU批次管理路由
提供批次管理页面渲染
"""
from flask import Blueprint, session, render_template, make_response
from app import db
from app.models import User
from app.utils.permission_decorators import page_permission_required

sku_batch_bp = Blueprint('sku_batch', __name__, url_prefix='/sku-batch')


@sku_batch_bp.after_request
def add_no_cache_headers(response):
    """确保HTML页面不被浏览器缓存"""
    if response.content_type and 'text/html' in response.content_type:
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response


@sku_batch_bp.route('/page')
@page_permission_required('sku_batch_view')
def sku_batch_page():
    """批次管理页面"""
    user = db.session.get(User, session.get('user_id'))
    user_permissions = []
    is_super = False
    if user:
        is_super = user.is_super
        if user.permissions:
            user_permissions = [p.code for p in user.permissions]
            for p in user.permissions:
                if p.children:
                    user_permissions.extend([c.code for c in p.children])
    return render_template('sku_batch.html',
                          user_permissions=user_permissions,
                          is_super=is_super)
