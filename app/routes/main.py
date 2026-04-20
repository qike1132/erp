"""
主路由蓝图
包含首页、登录、登出等基础路由
"""
from flask import Blueprint, render_template, redirect, url_for, session, make_response, request, flash, jsonify, current_app
from app import db, csrf, limiter
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
    # 静态资源由 Flask SEND_FILE_MAX_AGE_DEFAULT 控制（开发环境=0，不缓存）
    # 不再对此处设置长缓存，避免代码更新后浏览器仍使用旧版本
        
    # 添加 Permissions-Policy 头部，禁用所有敏感功能
    response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'

    return response


@main_bp.route('/')
def index():
    """首页"""
    if not session.get('user_id'):
        return redirect(url_for('main.login'))

    from app.models import Order, StockIn, StockOut, ApprovalRequest, Product, PurchaseOrder, MaterialRegistration
    from datetime import date, datetime

    today = date.today()
    today_start = datetime.combine(today, datetime.min.time())
    today_end = datetime.combine(today, datetime.max.time())

    # KPI 统计
    order_today = Order.query.filter(Order.order_date.between(today_start, today_end)).count()
    stockin_today = StockIn.query.filter(StockIn.stockin_date.between(today_start, today_end)).count()
    stockout_today = StockOut.query.filter(StockOut.stockout_date.between(today_start, today_end)).count()
    pending_approvals = ApprovalRequest.query.filter_by(status='pending').count()

    # 昨日对比
    from datetime import timedelta
    yesterday = today - timedelta(days=1)
    yesterday_start = datetime.combine(yesterday, datetime.min.time())
    yesterday_end = datetime.combine(yesterday, datetime.max.time())
    order_yesterday = Order.query.filter(Order.order_date.between(yesterday_start, yesterday_end)).count()
    stockin_yesterday = StockIn.query.filter(StockIn.stockin_date.between(yesterday_start, yesterday_end)).count()
    stockout_yesterday = StockOut.query.filter(StockOut.stockout_date.between(yesterday_start, yesterday_end)).count()

    # 待办事项
    low_stock_count = Product.query.filter(Product.current_stock <= 10, Product.current_stock >= 0).count()
    pending_purchases = PurchaseOrder.query.filter_by(status='pending').count()
    pending_materials = MaterialRegistration.query.filter(
        MaterialRegistration.status.in_(['pending', 'partial'])
    ).count()

    # 最近动态：合并最近 8 条记录
    recent_orders = [
        {'type': 'order', 'time': o.order_date, 'title': f'订单 {o.order_no}', 'status': o.status,
         'desc': f'{o.customer or ""}', 'id': o.id}
        for o in Order.query.order_by(Order.order_date.desc()).limit(4).all()
    ]
    recent_stockins = [
        {'type': 'stockin', 'time': s.stockin_date, 'title': f'备货 {s.stockin_no}', 'status': '备货完成',
         'desc': f'{s.customer or ""}', 'id': s.id}
        for s in StockIn.query.order_by(StockIn.stockin_date.desc()).limit(3).all()
    ]
    recent_stockouts = [
        {'type': 'stockout', 'time': s.stockout_date, 'title': f'出货 {s.stockout_no}', 'status': '出货完成',
         'desc': f'{s.customer or ""}', 'id': s.id}
        for s in StockOut.query.order_by(StockOut.stockout_date.desc()).limit(3).all()
    ]
    recent_approvals = [
        {'type': 'approval', 'time': a.request_time, 'title': f'审批 {a.id}',
         'status': '已同意' if a.status == 'approved' else '已拒绝' if a.status == 'rejected' else '待审批',
         'desc': a.operation_type or '', 'id': a.id}
        for a in ApprovalRequest.query.order_by(ApprovalRequest.request_time.desc()).limit(3).all()
    ]

    activities = recent_orders + recent_stockins + recent_stockouts + recent_approvals
    activities.sort(key=lambda x: x['time'] or datetime.min, reverse=True)
    activities = activities[:8]

    return render_template('index.html', is_home=True,
        order_today=order_today, stockin_today=stockin_today,
        stockout_today=stockout_today, pending_approvals=pending_approvals,
        order_yesterday=order_yesterday, stockin_yesterday=stockin_yesterday,
        stockout_yesterday=stockout_yesterday,
        low_stock_count=low_stock_count, pending_purchases=pending_purchases,
        pending_materials=pending_materials, activities=activities)


@main_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("5/minute")
def login():
    """登录"""
    from app.models import User
    from werkzeug.security import check_password_hash

    if not session.get('user_id'):
        remember_token = request.cookies.get('remember_token')
        if remember_token:
            try:
                from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
                serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='remember')
                data = serializer.loads(remember_token, max_age=2592000)  # 30天过期
                user_id = data.get('user_id')
                if user_id:
                    user = db.session.get(User, int(user_id))
                    if user and user.status:
                        # Session Fixation 防护：自动登录也需重新生成 Session ID
                        session.clear()
                        session['user_id'] = user.id
                        session['username'] = user.username
                        session['is_super'] = user.is_super
                        return redirect(url_for('main.index'))
            except (BadSignature, SignatureExpired):
                pass

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
        if not user or not user.status or not check_password_hash(user.password, password):
            flash('用户名或密码错误', 'error')
            return render_template('login.html')

        # Session Fixation 防护：登录成功后重新生成 Session ID
        old_session_data = dict(session)
        session.clear()
        session.update(old_session_data)
        session['user_id'] = user.id
        session['username'] = user.username
        session['is_super'] = user.is_super
        flash('登录成功', 'success')
        if remember:
            from itsdangerous import URLSafeTimedSerializer
            serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='remember')
            token = serializer.dumps({'user_id': user.id})
            resp = make_response(redirect(url_for('main.index')))
            resp.set_cookie('remember_token', token,
                          httponly=True, secure=request.is_secure, samesite='Lax',
                          max_age=2592000)  # 30天过期
            return resp
        return redirect(url_for('main.index'))

    return render_template('login.html')


@main_bp.route('/logout', methods=['POST'])
def logout():
    """退出登录"""
    session.clear()
    resp = make_response(redirect(url_for('main.login')))
    resp.set_cookie('remember_token', '', max_age=0)
    return resp


@csrf.exempt
@main_bp.route('/api/login', methods=['POST'])
@limiter.limit("5/minute")
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
        if not user or not user.status or not check_password_hash(user.password, password):
            return jsonify({'success': False, 'error': '用户名或密码错误'}), 401

        # Session Fixation 防护：登录成功后重新生成 Session ID
        old_session_data = dict(session)
        session.clear()
        session.update(old_session_data)
        session['user_id'] = user.id
        session['username'] = user.username
        session['is_super'] = user.is_super

        response_data = {'success': True, 'message': '登录成功'}
        resp = make_response(jsonify(response_data))

        if remember:
            from itsdangerous import URLSafeTimedSerializer
            serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='remember')
            token = serializer.dumps({'user_id': user.id})
            resp.set_cookie('remember_token', token,
                          httponly=True, secure=request.is_secure, samesite='Lax',
                          max_age=2592000)  # 30天过期

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
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': '未登录'}), 401
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
