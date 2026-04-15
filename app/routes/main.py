"""
主路由蓝图
包含首页、登录、登出等基础路由
"""
from flask import Blueprint, render_template, redirect, url_for, session, make_response, request, flash, jsonify, current_app
from app import db, csrf
from functools import wraps
from utils.sanitizer import sanitize_plain_text

main_bp = Blueprint('main', __name__)


@main_bp.after_request
def add_cache_headers(response):
    """添加缓存控制响应头"""
    # 只对 HTML 页面添加禁止缓存头，确保页面总是加载最新版本
    if response.content_type and 'text/html' in response.content_type:
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    # 对静态资源（CSS, JS, 图片等）添加强缓存 (30天)
    elif request.path.startswith('/static/'):
        response.headers['Cache-Control'] = 'public, max-age=2592000'
        
    # 添加 Permissions-Policy 头部，禁用所有敏感功能
    response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'

    return response


@main_bp.route('/')
def index():
    """首页"""
    if not session.get('user_id'):
        return redirect(url_for('main.login'))
    return render_template('index.html', is_home=True)


@main_bp.route('/test-js')
def test_js():
    """JavaScript测试页面"""
    return render_template('test_js.html')


@main_bp.route('/login', methods=['GET', 'POST'])
def login():
    """登录"""
    from app.models import User
    from werkzeug.security import check_password_hash

    if not session.get('user_id'):
        user_id = request.cookies.get('user_id')
        if user_id:
            user = db.session.get(User, int(user_id))
            if user and user.status:
                session['user_id'] = user.id
                session['username'] = user.username
                session['is_super'] = user.is_super
                session['permissions'] = [p.code for p in user.permissions]
                return redirect(url_for('main.index'))

    if session.get('user_id'):
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        username = sanitize_plain_text(request.form.get('username', '').strip())
        password = request.form.get('password', '')

        if not username or not password:
            flash('请输入用户名和密码', 'error')
            return render_template('login.html')

        if len(password) > 128:
            flash('密码长度不能超过128位', 'error')
            return render_template('login.html')
        remember = request.form.get('remember') == 'on'

        user = User.query.filter_by(username=username).first()
        if not user:
            flash('用户名不存在', 'error')
            return render_template('login.html')
        if not user.status:
            flash('账号已被禁用，请联系管理员', 'error')
            return render_template('login.html')
        if not check_password_hash(user.password, password):
            flash('密码错误，请重新输入', 'error')
            return render_template('login.html')

        session['user_id'] = user.id
        session['username'] = user.username
        session['is_super'] = user.is_super
        session['permissions'] = [p.code for p in user.permissions]
        flash('登录成功', 'success')
        if remember:
            resp = make_response(redirect(url_for('main.index')))
            resp.set_cookie('user_id', str(user.id), max_age=30*24*60*60)
            return resp
        return redirect(url_for('main.index'))

    return render_template('login.html')


@main_bp.route('/logout')
def logout():
    """退出登录"""
    session.clear()
    resp = make_response(redirect(url_for('main.login')))
    resp.set_cookie('user_id', '', max_age=0)
    return resp


@csrf.exempt
@main_bp.route('/api/login', methods=['POST'])
def api_login():
    """AJAX登录API

    [已迁移至 FastAPI] 新代码请使用 POST /api/v1/auth/login (JWT模式)
    本路由保留用于浏览器session登录兼容
    """
    from app.models import User
    from werkzeug.security import check_password_hash

    try:
        data = request.get_json()
        username = sanitize_plain_text(data.get('username', '').strip())
        password = data.get('password', '')
        remember = data.get('remember', False)

        if not username or not password:
            return jsonify({'success': False, 'error': '请输入用户名和密码'}), 400

        if len(password) > 128:
            return jsonify({'success': False, 'error': '密码长度不能超过128位'}), 400

        user = User.query.filter_by(username=username).first()
        if not user:
            return jsonify({'success': False, 'error': '用户名不存在'}), 401
        if not user.status:
            return jsonify({'success': False, 'error': '账号已被禁用，请联系管理员'}), 401
        if not check_password_hash(user.password, password):
            return jsonify({'success': False, 'error': '密码错误，请重新输入'}), 401

        session['user_id'] = user.id
        session['username'] = user.username
        session['is_super'] = user.is_super
        session['permissions'] = [p.code for p in user.permissions]

        response_data = {'success': True, 'message': '登录成功'}
        resp = make_response(jsonify(response_data))

        if remember:
            resp.set_cookie('user_id', str(user.id), max_age=30*24*60*60)

        return resp, 200

    except Exception as e:
        return jsonify({'success': False, 'error': '服务器错误，请稍后重试'}), 500


# ==================== 兼容性路由 ====================
# 为了兼容旧模板中的路由名称，添加以下兼容性路由

@main_bp.route('/products')
def products():
    """兼容性路由：产品管理"""
    return redirect(url_for('product.products'))


@main_bp.route('/orders')
def orders():
    """兼容性路由：订单管理"""
    return redirect(url_for('order.orders'))


@main_bp.route('/stockins')
def stockins():
    """兼容性路由：入库管理"""
    return redirect(url_for('stock.stockins'))


@main_bp.route('/stockouts')
def stockouts():
    """兼容性路由：出库管理"""
    return redirect(url_for('stock.stockouts'))


@main_bp.route('/inventory')
def inventory():
    """兼容性路由：库存查看"""
    return redirect(url_for('stock.inventory'))


@main_bp.route('/reports')
def reports():
    """兼容性路由：报表统计"""
    return redirect(url_for('report.reports'))


@main_bp.route('/cases')
def cases():
    """兼容性路由：案件管理"""
    # TODO: 实现案件管理功能
    flash('案件管理功能开发中...', 'info')
    return redirect(url_for('main.index'))


@main_bp.route('/users')
def users():
    """兼容性路由：用户管理"""
    # TODO: 实现用户管理功能
    flash('用户管理功能开发中...', 'info')
    return redirect(url_for('main.index'))


# ==================== 批量导入兼容性路由 ====================
# 已迁移至 FastAPI: /api/v1/batch/*
# 前端已更新为直接调用 FastAPI 端点，以下兼容性路由已移除


@csrf.exempt
@main_bp.route('/upload', methods=['POST'])
def upload_file():
    """图片上传路由

    [已迁移至 FastAPI] 新代码请使用 POST /api/v1/auth/upload
    """
    import os
    from werkzeug.utils import secure_filename
    from flask import jsonify
    
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': '没有选择文件'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'error': '没有选择文件'}), 400
        
        # 检查文件类型
        allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
        filename = secure_filename(file.filename)
        if '.' not in filename or filename.rsplit('.', 1)[1].lower() not in allowed_extensions:
            return jsonify({'success': False, 'error': '不支持的文件类型'}), 400
        
        # 生成唯一文件名
        from datetime import datetime
        import uuid
        ext = filename.rsplit('.', 1)[1].lower()
        new_filename = f"{datetime.now().strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}.{ext}"
        
        upload_folder = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'static', 'uploads')
        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder)
        
        file_path = os.path.join(upload_folder, new_filename)
        file.save(file_path)
        
        # 返回可访问的URL
        file_url = f"/static/uploads/{new_filename}"
        return jsonify({'success': True, 'url': file_url, 'filename': new_filename})
    
    except Exception as e:
        current_app.logger.error(f"文件上传失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': '文件上传失败，请稍后重试'}), 500
