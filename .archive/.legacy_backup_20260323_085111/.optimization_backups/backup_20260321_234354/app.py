import os
import shutil
import uuid
from datetime import datetime, timedelta
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, flash, jsonify, make_response, redirect, render_template, request, session, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import func
from sqlalchemy.orm import joinedload, selectinload
from werkzeug.security import check_password_hash, generate_password_hash

# 加载环境变量
load_dotenv()

app = Flask(__name__)
# 从环境变量读取密钥,不提供默认值以确保安全
app.secret_key = os.getenv('SECRET_KEY')
if not app.secret_key:
    raise ValueError('SECRET_KEY environment variable is required. Please set it in .env file')

# 启用CSRF保护
csrf = CSRFProtect(app)

# 为API路由禁用CSRF保护
@csrf.exempt
def exempt_api_routes():
    pass

# 获取CSRF实例以便后续使用
def get_csrf():
    return csrf
# 配置上传路径
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')
# 创建上传目录
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}
# 图片上传配置
app.config['MAX_IMAGE_SIZE'] = 1024  # 最大尺寸1024像素
app.config['MAX_FILE_SIZE'] = 2  # 最大文件大小2MB
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}
# 配置数据库（支持 SQLite 和 MySQL）
# 从环境变量读取数据库配置，默认使用 SQLite
db_type = os.getenv('DB_TYPE', 'mysql')
db_host = os.getenv('DB_HOST', 'localhost')
db_port = os.getenv('DB_PORT', '3306')
db_user = os.getenv('DB_USER', 'root')
db_password = os.getenv('DB_PASSWORD')  # 不提供默认密码,必须从环境变量读取
if db_type == 'mysql' and not db_password:
    raise ValueError('DB_PASSWORD environment variable is required for MySQL. Please set it in .env file')
db_name = os.getenv('DB_NAME', 'erp_system')

if db_type == 'mysql':
    # MySQL 数据库配置
    app.config['SQLALCHEMY_DATABASE_URI'] = f'mysql+pymysql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}?charset=utf8mb4'
    # MySQL连接池配置
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_size': 10,          # 连接池大小
        'max_overflow': 20,       # 最大溢出连接数
        'pool_recycle': 3600,     # 连接回收时间(秒)
        'pool_pre_ping': True,    # 连接前检查可用性
        'echo': False             # 不输出SQL日志
    }
else:
    # SQLite 数据库配置（默认）
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///erp.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# region agent log
try:
    import json as _agent_json
    import time as _agent_time
    from pathlib import Path as _agent_Path

    def _agent_log(hypothesis_id, location, message, data):
        try:
            entry = {
                "sessionId": "7cd190",
                "runId": "deduct-debug",
                "hypothesisId": hypothesis_id,
                "location": location,
                "message": message,
                "data": data or {},
                "timestamp": int(_agent_time.time() * 1000),
            }
            log_path = _agent_Path("debug-7cd190.log")
            with log_path.open("a", encoding="utf-8") as f:
                f.write(_agent_json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass
except Exception:
    def _agent_log(*args, **kwargs):
        pass
# endregion

# 数据库模型定义
class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, index=True, comment='产品名称')  # 添加索引
    barcode = db.Column(db.String(50), index=True, comment='69码/商品条码')  # 添加索引
    image = db.Column(db.String(200), comment='产品图片路径')
    initial_stock = db.Column(db.Integer, default=0, comment='初始库存')
    current_stock = db.Column(db.Integer, default=0, comment='当前库存')
    create_time = db.Column(db.DateTime, default=datetime.now, index=True, comment='创建时间')  # 添加索引

    def __repr__(self):
        return f'<Product {self.name}>'

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_no = db.Column(db.String(20), unique=True, nullable=False, comment='订单时间')
    customer = db.Column(db.String(100), nullable=False, index=True, comment='客户名称')  # 添加索引
    order_date = db.Column(db.DateTime, default=datetime.now, index=True, comment='下单时间')  # 添加索引
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False, index=True, comment='产品ID')  # 添加索引
    quantity = db.Column(db.Integer, nullable=False, comment='订单数量')
    status = db.Column(db.String(20), default='待备货', index=True, comment='订单状态：待备货、部分备货、已备货、待出货、已出货、已取消')  # 添加索引
    note = db.Column(db.Text, comment='备注')
    product = db.relationship('Product', backref=db.backref('orders', lazy=True))

    def __repr__(self):
        return f'<Order {self.order_no}>'

class StockIn(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    stockin_no = db.Column(db.String(20), unique=True, nullable=False, comment='备货编号')
    stockin_date = db.Column(db.DateTime, default=datetime.now, index=True, comment='备货时间')  # 添加索引
    customer = db.Column(db.String(100), nullable=False, index=True, comment='客户名称')  # 添加索引
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False, index=True, comment='产品ID')  # 添加索引
    quantity = db.Column(db.Integer, nullable=False, comment='备货数量')
    note = db.Column(db.Text, comment='备注')
    product = db.relationship('Product', backref=db.backref('stockins', lazy=True))

    def __repr__(self):
        return f'<StockIn {self.stockin_no}>'

class StockOut(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    stockout_no = db.Column(db.String(20), unique=True, nullable=False, comment='出货编号')
    stockout_date = db.Column(db.DateTime, default=datetime.now, index=True, comment='出货时间')  # 添加索引
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False, index=True, comment='产品 ID')  # 添加索引
    quantity = db.Column(db.Integer, nullable=False, comment='出货数量')
    customer = db.Column(db.String(100), nullable=True, index=True, comment='客户名称')  # 添加索引
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=True, index=True, comment='关联订单 ID')  # 添加索引
    stockin_id = db.Column(db.Integer, db.ForeignKey('stock_in.id'), index=True, comment='关联备货 ID')  # 添加索引
    note = db.Column(db.Text, comment='备注')
    product = db.relationship('Product', backref=db.backref('stockouts', lazy=True))
    order = db.relationship('Order', backref=db.backref('stockouts', lazy=True))
    stockin = db.relationship('StockIn', backref=db.backref('stockouts', lazy=True))

class InventoryLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id', ondelete='CASCADE'), nullable=False, index=True, comment='产品ID')  # 添加索引
    change_type = db.Column(db.String(20), nullable=False, index=True, comment='变化类型：初始库存、备货、出货、订单调整')  # 添加索引
    change_quantity = db.Column(db.Integer, nullable=False, comment='变化数量（正数为增加，负数为减少）')
    change_date = db.Column(db.DateTime, default=datetime.now, index=True, comment='变化时间')  # 添加索引
    related_id = db.Column(db.String(50), comment='关联单据编号')
    note = db.Column(db.Text, comment='备注')
    customer = db.Column(db.String(100), nullable=True, index=True, comment='客户名称')  # 添加索引
    product = db.relationship('Product', backref=db.backref('inventory_logs', lazy=True))

class Case(db.Model):
    __tablename__ = 'case'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, index=True, comment='皮套名称')  # 添加索引
    barcode = db.Column(db.String(50), index=True, comment='69 码/皮套条码')  # 添加索引
    image = db.Column(db.String(200), comment='皮套图片路径')
    initial_stock = db.Column(db.Integer, default=0, comment='初始库存')
    current_stock = db.Column(db.Integer, default=0, comment='当前库存')
    create_time = db.Column(db.DateTime, default=datetime.now, index=True, comment='创建时间')  # 添加索引

    def __repr__(self):
        return f'<Case {self.name}>'

class CaseStockIn(db.Model):
    __tablename__ = 'case_stock_in'
    id = db.Column(db.Integer, primary_key=True)
    stockin_no = db.Column(db.String(20), unique=True, nullable=False, comment='入库编号')
    stockin_date = db.Column(db.DateTime, default=datetime.now, comment='入库时间')
    customer = db.Column(db.String(100), nullable=False, comment='客户名称')
    case_id = db.Column(db.Integer, db.ForeignKey('case.id'), nullable=False, comment='皮套 ID')
    quantity = db.Column(db.Integer, nullable=False, comment='入库数量')
    note = db.Column(db.Text, comment='备注')
    case = db.relationship('Case', backref=db.backref('stockins', lazy=True))

    def __repr__(self):
        return f'<CaseStockIn {self.stockin_no}>'

class CaseStockOut(db.Model):
    __tablename__ = 'case_stock_out'
    id = db.Column(db.Integer, primary_key=True)
    stockout_no = db.Column(db.String(20), unique=True, nullable=False, comment='出库编号')
    stockout_date = db.Column(db.DateTime, default=datetime.now, comment='出库时间')
    case_id = db.Column(db.Integer, db.ForeignKey('case.id'), nullable=False, comment='皮套 ID')
    quantity = db.Column(db.Integer, nullable=False, comment='出库数量')
    customer = db.Column(db.String(100), nullable=True, comment='客户名称')
    stockin_id = db.Column(db.Integer, db.ForeignKey('case_stock_in.id'), comment='关联入库 ID')
    note = db.Column(db.Text, comment='备注')
    case = db.relationship('Case', backref=db.backref('stockouts', lazy=True))
    stockin = db.relationship('CaseStockIn', backref=db.backref('stockouts', lazy=True))

    def __repr__(self):
        return f'<CaseStockOut {self.stockout_no}>'

class CaseInventoryLog(db.Model):
    __tablename__ = 'case_inventory_log'
    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.Integer, db.ForeignKey('case.id', ondelete='CASCADE'), nullable=False, comment='皮套 ID')
    change_type = db.Column(db.String(20), nullable=False, comment='变化类型：初始库存、入库、出库、调整')
    change_quantity = db.Column(db.Integer, nullable=False, comment='变化数量（正数为增加，负数为减少）')
    change_date = db.Column(db.DateTime, default=datetime.now, comment='变化时间')
    related_id = db.Column(db.String(20), comment='关联单据编号')
    note = db.Column(db.Text, comment='备注')
    customer = db.Column(db.String(100), nullable=True, comment='客户名称')
    case = db.relationship('Case', backref=db.backref('inventory_logs', lazy=True))

    def __repr__(self):
        return f'<CaseInventoryLog {self.id}>'

# 用户管理模型
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False, comment='用户名')
    password = db.Column(db.String(200), nullable=False, comment='密码')
    is_super = db.Column(db.Boolean, default=False, comment='是否超级用户')
    status = db.Column(db.Boolean, default=True, comment='是否启用')
    create_time = db.Column(db.DateTime, default=datetime.now, comment='创建时间')
    update_time = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')
    permissions = db.relationship('Permission', secondary='user_permission', backref=db.backref('users', lazy=True))

    def __repr__(self):
        return f'<User {self.username}>'

    def has_permission(self, permission_code):
        # 超级用户拥有所有权限
        if self.is_super:
            return True
        # 普通用户检查是否有对应权限
        return any(p.code == permission_code for p in self.permissions)

class Permission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, comment='权限名称')
    code = db.Column(db.String(50), unique=True, nullable=False, comment='权限标识')
    parent_id = db.Column(db.Integer, db.ForeignKey('permission.id'), comment='父权限ID')
    parent = db.relationship('Permission', remote_side=[id], backref=db.backref('children', lazy=True))

    def __repr__(self):
        return f'<Permission {self.name}>'

# 用户权限关联表
user_permission = db.Table('user_permission',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('permission_id', db.Integer, db.ForeignKey('permission.id'), primary_key=True)
)

# 注册datetime到模板全局，解决模板中datetime未定义的问题
app.jinja_env.globals['datetime'] = datetime
# 权限验证装饰器
def permission_required(permission_code):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not session.get('user_id'):
                return redirect(url_for('login'))
            user = User.query.get(session['user_id'])
            if not user:
                # 用户不存在，清除 session 并重定向到登录页
                session.clear()
                return redirect(url_for('login'))
            if user.is_super:
                return f(*args, **kwargs)
            # 检查用户是否有该权限
            has_permission = False
            for p in user.permissions:
                if p.code == permission_code:
                    has_permission = True
                    break
            if not has_permission:
                flash('无权限访问该页面', 'error')
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def api_permission_required(permission_code):
    """API专用的权限装饰器，返回JSON响应而不是HTML重定向"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not session.get('user_id'):
                return jsonify({
                    'success': False,
                    'error': '未登录',
                    'message': '请先登录'
                }), 401
            user = User.query.get(session['user_id'])
            if not user:
                session.clear()
                return jsonify({
                    'success': False,
                    'error': '用户不存在',
                    'message': '用户信息无效，请重新登录'
                }), 401
            if user.is_super:
                return f(*args, **kwargs)
            # 检查用户是否有该权限
            has_permission = False
            for p in user.permissions:
                if p.code == permission_code:
                    has_permission = True
                    break
            if not has_permission:
                return jsonify({
                    'success': False,
                    'error': '无权限',
                    'message': '您没有权限执行此操作'
                }), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator


# 路由定义
# 登录路由
@app.route('/login', methods=['GET', 'POST'])
def login():
    # 检查cookie中是否有用户信息，实现自动登录
    if not session.get('user_id'):
        user_id = request.cookies.get('user_id')
        if user_id:
            user = User.query.get(int(user_id))
            if user and user.status:
                session['user_id'] = user.id
                session['username'] = user.username
                session['is_super'] = user.is_super
                session['permissions'] = [p.code for p in user.permissions]
                return redirect(url_for('index'))
    if session.get('user_id'):
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        remember = request.form.get('remember') == 'on'
        user = User.query.filter_by(username=username, status=True).first()
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['username'] = user.username
            session['is_super'] = user.is_super
            # 将用户的权限列表存入session，用于模板判断
            session['permissions'] = [p.code for p in user.permissions]
            flash('登录成功', 'success')
            # 如果勾选了记住我，设置cookie
            if remember:
                resp = make_response(redirect(url_for('index')))
                resp.set_cookie('user_id', str(user.id), max_age=30*24*60*60)  # 30天过期
                return resp
            return redirect(url_for('index'))
        else:
            flash('用户名或密码错误', 'error')
    return render_template('login.html')

# 退出登录路由
@app.route('/logout')
def logout():
    session.clear()
    # 清除cookie，直接重定向到登录页面，不显示任何通知
    resp = make_response(redirect(url_for('login')))
    resp.set_cookie('user_id', '', max_age=0)
    return resp

@app.after_request
def add_no_cache_headers(response):
    """添加禁止缓存的响应头，确保页面总是加载最新版本"""
    # 只对 HTML 页面添加禁止缓存头
    if response.content_type and 'text/html' in response.content_type:
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    # 添加 Permissions-Policy 头部，移除 browsing-topics 警告
    response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
    return response

@app.route('/')
def index():
    if not session.get('user_id'):
        return redirect(url_for('login'))
    return render_template('index.html', is_home=True)

# 产品管理
@app.route('/products', methods=['GET', 'POST'])
@api_permission_required('product_manage')
def products():
    if request.method == 'POST':
        name = request.form['name']
        barcode = request.form['barcode']
        image = request.form.get('image', '')
        initial_stock = int(request.form.get('initial_stock', 0))
        # 创建产品
        product = Product(name=name, barcode=barcode, image=image, initial_stock=initial_stock, current_stock=initial_stock)
        db.session.add(product)
        # 先刷新会话获取自增的产品ID，解决product_id为None的报错
        db.session.flush()
        # 添加库存日志（仅当初始库存>0时）
        if initial_stock > 0:
            log = InventoryLog(product_id=product.id, change_type='初始库存', change_quantity=initial_stock, related_id=str(product.id), note='初始库存设置')
            db.session.add(log)
        db.session.commit()
        flash('产品添加成功！', 'success')
        return redirect(url_for('products'))
    products = Product.query.all()
    return render_template('product.html', products=products)

@app.route('/product/edit/<int:id>', methods=['GET', 'POST'])
@api_permission_required('product_manage')
def edit_product(id):
    product = Product.query.get_or_404(id)
    if request.method == 'POST':
        product.name = request.form['name']
        product.barcode = request.form['barcode']
        product.image = request.form.get('image', product.image)
        # 初始库存调整（仅当表单中提供此字段时）
        if 'initial_stock' in request.form:
            new_initial = int(request.form['initial_stock'])
            stock_change = new_initial - product.initial_stock
            if stock_change != 0:
                product.initial_stock = new_initial
                product.current_stock += stock_change
                # 添加库存日志
                log = InventoryLog(product_id=product.id, change_type='初始库存调整', change_quantity=stock_change, related_id=str(product.id), note='初始库存调整')
                db.session.add(log)
        db.session.commit()
        flash('产品编辑成功！', 'success')
        return redirect(url_for('products'))
    return render_template('edit_product.html', product=product)

@app.route('/product/delete/<int:id>')
@api_permission_required('product_manage')
def delete_product(id):
    product = Product.query.get_or_404(id)
    # 检查是否有相关单据
    if product.orders or product.stockins or product.stockouts:
        flash('该产品已有相关单据，无法删除！', 'error')
        return redirect(url_for('products'))
    # 先删除相关的库存日志
    for log in product.inventory_logs:
        db.session.delete(log)
    db.session.delete(product)
    db.session.commit()
    flash('产品删除成功！', 'success')
    return redirect(url_for('products'))

# 辅助函数：检查文件扩展名
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

# 图片上传处理
@app.route('/upload', methods=['POST'])
@api_permission_required('product_manage')
def upload_image():
    try:
        if 'file' not in request.files:
            return jsonify({'error': '没有文件'}), 400
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': '没有选择文件'}), 400
        if not allowed_file(file.filename):
            return jsonify({'error': '不支持的文件格式'}), 400

        # 检查文件大小
        file.seek(0, os.SEEK_END)
        file_size = file.tell() / (1024 * 1024)
        file.seek(0)
        if file_size > app.config['MAX_FILE_SIZE']:
            return jsonify({'error': f'文件大小不能超过{app.config["MAX_FILE_SIZE"]}MB'}), 400

        # 生成唯一文件名
        ext = file.filename.rsplit('.', 1)[1].lower()
        filename = f'{uuid.uuid4().hex}.{ext}'
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)

        # 尝试使用Pillow压缩图片
        try:
            from PIL import Image
            img = Image.open(file)

            # 计算新尺寸，保持宽高比
            max_size = app.config['MAX_IMAGE_SIZE']
            if img.width > max_size or img.height > max_size:
                ratio = min(max_size / img.width, max_size / img.height)
                new_width = int(img.width * ratio)
                new_height = int(img.height * ratio)
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

            # 保存图片，根据格式调整质量
            if ext in ['jpg', 'jpeg']:
                img.save(filepath, 'JPEG', quality=85, optimize=True)
            elif ext == 'png':
                img.save(filepath, 'PNG', optimize=True)
            else:
                img.save(filepath)
        except ImportError:
            # 如果没有Pillow，直接保存原文件
            file.save(filepath)
        except Exception:
            # 如果处理出错，直接保存原文件
            file.seek(0)
            file.save(filepath)

        # 返回文件URL
        file_url = url_for('static', filename=f'uploads/{filename}')
        return jsonify({'url': file_url})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# 导入统一的工具函数
import contextlib

from utils.decorators import (
    api_error,
)
from utils.number_generator import (
    generate_case_stockin_number,
    generate_case_stockout_number,
    generate_order_number,
    generate_stockin_number,
    generate_stockout_number,
)


def process_order_deduction(order, product_id, order_quantity, deduct_stock=True, custom_deduct_quantity=None):
    """
    处理订单抵扣备货的核心逻辑

    参数:
        order: Order对象，订单实例
        product_id: int，产品ID
        order_quantity: int，订单数量
        deduct_stock: bool，是否执行抵扣，默认True
        custom_deduct_quantity: int，自定义抵扣数量，None表示抵扣全部

    返回:
        int: 实际抵扣的总数量
    """
    if not deduct_stock:
        return 0

    _agent_log("H1", "process_order_deduction:start", "Begin deduction flow", {
        "order_id": order.id,
        "product_id": product_id,
        "order_quantity": order_quantity,
        "custom_deduct_quantity": custom_deduct_quantity,
        "order_customer": order.customer,
    })

    # 查询该产品的备货记录，按客户匹配，按时间升序（FIFO原则）
    # 重要：订单只能抵扣相同客户的备货
    stockins = StockIn.query.filter_by(
        product_id=product_id,
        customer=order.customer  # 添加客户匹配条件
    ).order_by(
        StockIn.stockin_date.asc(),
        StockIn.id.asc()
    ).all()

    # 计算总可用备货数量（需要减去已抵扣的数量）
    total_quantity = 0
    for stockin in stockins:
        # 计算该备货记录的已抵扣数量
        deducted = sum(s.quantity for s in stockin.stockouts) if stockin.stockouts else 0
        available = stockin.quantity - deducted
        total_quantity += available

    _agent_log("H2", "process_order_deduction:available", "Computed total available stockins", {
        "total_available": total_quantity,
        "order_quantity": order_quantity,
        "stockins_count": len(stockins),
        "custom_deduct_quantity": custom_deduct_quantity,
        "order_customer": order.customer,
    })

    # 确定需要抵扣的数量
    if custom_deduct_quantity is not None and custom_deduct_quantity > 0:
        remaining_to_deduct = min(custom_deduct_quantity, order_quantity, total_quantity)
    else:
        remaining_to_deduct = min(order_quantity, total_quantity)

    total_deducted = 0

    # 按FIFO原则从备货记录中抵扣
    for stockin in stockins:
        if remaining_to_deduct <= 0:
            break

        # 计算该备货记录的已抵扣数量
        deducted = sum(s.quantity for s in stockin.stockouts) if stockin.stockouts else 0
        available = stockin.quantity - deducted

        if available <= 0:
            continue

        deduct_amount = min(remaining_to_deduct, available)

        _agent_log("H2", "process_order_deduction:loop", "Deduct from single stockin", {
            "stockin_id": stockin.id,
            "stockin_quantity": stockin.quantity,
            "already_deducted": deducted,
            "available": available,
            "deduct_amount": deduct_amount,
            "remaining_to_deduct_before": remaining_to_deduct,
        })

        # 创建出货记录（仅用于记录抵扣关系，不显示在出货管理中）
        # 通过设置特殊的note标识，在出货管理中过滤掉这些记录
        stockout = StockOut(
            stockout_no=f'DEDUCT-{datetime.now().strftime("%Y%m%d%H%M%S%f")}',
            stockout_date=datetime.now(),
            product_id=stockin.product_id,
            quantity=deduct_amount,
            customer=order.customer,  # 添加客户信息
            order_id=order.id,
            stockin_id=stockin.id,
            note=f'[订单抵扣]{order.order_no}'  # 使用特殊标识
        )
        db.session.add(stockout)

        # 抵扣时减少产品当前库存
        stockin.product.current_stock -= deduct_amount

        # 添加库存日志
        log = InventoryLog(
            product_id=stockin.product_id,
            change_type='订单抵扣',
            change_quantity=-deduct_amount,
            related_id=stockout.stockout_no,
            note=f'订单抵扣备货：{stockin.stockin_no}'
        )
        db.session.add(log)

        total_deducted += deduct_amount
        remaining_to_deduct -= deduct_amount

    # 根据抵扣结果更新订单状态
    if total_deducted >= order_quantity:
        order.status = '已备货'
    elif total_deducted > 0:
        order.status = '部分备货'
    else:
        order.status = '待备货'

    _agent_log("H3", "process_order_deduction:end", "Finished deduction flow", {
        "total_deducted": total_deducted,
        "final_order_status": order.status,
    })

    return total_deducted

# 订单管理
@app.route('/orders', methods=['GET', 'POST'])
@api_permission_required('order_manage')
def orders():
    if request.method == 'POST':
        _agent_log("H1", "orders:POST:start", "Start creating order", {
            "form_product_id": request.form.get('product_id'),
            "form_quantity": request.form.get('quantity'),
            "deduct_stock_flag": request.form.get('deduct_stock'),
        })
        # 自动生成订单时间，不使用前端传来的值
        order_no = generate_order_number(db, Order)

        # 验证必填字段
        product_id_str = request.form.get('product_id', '').strip()
        quantity_str = request.form.get('quantity', '').strip()

        if not product_id_str:
            flash('请选择产品！', 'error')
            return redirect(url_for('orders'))
        if not quantity_str or quantity_str == '0':
            flash('请输入有效的数量！', 'error')
            return redirect(url_for('orders'))

        try:
            product_id = int(product_id_str)
            quantity = int(quantity_str)
        except ValueError:
            flash('产品ID和数量必须是有效的整数！', 'error')
            return redirect(url_for('orders'))

        note = request.form['note']
        customer = request.form['customer']
        order_date = datetime.now()

        # 检查订单时间是否已存在
        existing_order = Order.query.filter_by(order_no=order_no).first()
        if existing_order:
            flash('订单时间已存在！', 'error')
            return redirect(url_for('orders'))
        # 检查产品是否存在
        product = Product.query.get(product_id)
        if not product:
            flash('产品不存在！', 'error')
            return redirect(url_for('orders'))

        # 创建订单（初始状态为待备货）
        order = Order(
            order_no=order_no,
            customer=customer,
            order_date=order_date,
            product_id=product_id,
            quantity=quantity,
            note=note,
            status='待备货'
        )
        db.session.add(order)
        db.session.flush()

        # 订单增加库存
        product.current_stock += quantity
        # 添加订单增加库存的日志
        log_order = InventoryLog(
            product_id=product_id,
            change_type='订单',
            change_quantity=quantity,
            related_id=order_no,
            note=f'订单：{order_no}'
        )
        db.session.add(log_order)

        # 是否执行抵扣备货逻辑由前端抵扣备货按钮控制
        deduct_stock = request.form.get('deduct_stock') == 'on'

        # 检查是否有自定义抵扣数量
        custom_deduct_quantity = None
        deduct_stockins = request.form.get('deduct_stockins', '')
        if deduct_stockins:
            try:
                import json
                stockin_data = json.loads(deduct_stockins)
                if stockin_data and isinstance(stockin_data, list):
                    for item in stockin_data:
                        if isinstance(item, dict) and item.get('id') == 'custom' and 'quantity' in item:
                            custom_deduct_quantity = int(item['quantity'])
                            break
            except Exception as e:
                _agent_log("H1", "orders:POST:deduct_error", "Failed to parse deduct_stockins", {"error": str(e)})

        # 调用抵扣函数
        if deduct_stock:
            process_order_deduction(
                order=order,
                product_id=product_id,
                order_quantity=quantity,
                deduct_stock=True,
                custom_deduct_quantity=custom_deduct_quantity
            )

        db.session.commit()
        flash('订单添加成功！', 'success')
        return redirect(url_for('orders'))
        db.session.commit()
        flash('订单添加成功！', 'success')
        return redirect(url_for('orders'))

    # GET 请求时，预生成一个订单时间供前端显示
    orders = Order.query.all()
    products = Product.query.all()
    preview_order_no = generate_order_number(db, Order)

    # 将Order对象转换为可序列化的字典
    orders_data = []
    for order in orders:
        order_dict = {
            'id': order.id,
            'order_no': order.order_no,
            'customer': order.customer,
            'order_date': order.order_date.strftime('%Y-%m-%d') if order.order_date else '',
            'quantity': order.quantity,
            'note': order.note or '',
            'status': order.status,
            'product': {
                'id': order.product.id,
                'name': order.product.name,
                'barcode': order.product.barcode or '',
                'image': order.product.image or ''
            }
        }
        orders_data.append(order_dict)

    return render_template('order.html', orders=orders_data, products=products, preview_order_no=preview_order_no)

# 测试接口 - 简化版本
@csrf.exempt
@app.route('/api/test-simple-submit', methods=['POST'])
@api_permission_required('order_manage')
def test_simple_submit():
    """
    简化的测试接口
    """
    print('=== test_simple_submit called ===')
    try:
        data = request.get_json()
        print('Received data:', data)
        return jsonify({
            'success': True,
            'message': '测试成功！',
            'data': data
        })
    except Exception as e:
        print('Error:', str(e))
        import traceback
        print('Traceback:', traceback.format_exc())
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500

# 批量提交订单API
@app.route('/api/batch-submit-orders', methods=['POST'])
@csrf.exempt
@api_permission_required('order_manage')
def batch_submit_orders():
    """
    批量提交订单API，返回JSON响应而不是重定向
    """
    try:
        data = request.get_json()
        orders_data = data.get('orders', [])

        if not orders_data:
            return jsonify({
                'success': False,
                'message': '没有订单数据'
            })

        success_count = 0
        failed_orders = []

        for order_data in orders_data:
            try:
                # 完全按照原始代码的逻辑执行
                order_no = generate_order_number(db, Order)

                product_id_str = str(order_data.get('productId', '')).strip()
                quantity_str = str(order_data.get('quantity', '')).strip()
                note = order_data.get('note', '')
                customer = order_data.get('customer', '')

                if not product_id_str:
                    failed_orders.append({'order': order_data, 'error': '请选择产品'})
                    continue

                if not quantity_str or quantity_str == '0':
                    failed_orders.append({'order': order_data, 'error': '请输入有效的数量'})
                    continue

                product_id = int(product_id_str)
                quantity = int(quantity_str)

                product = Product.query.get(product_id)
                if not product:
                    failed_orders.append({'order': order_data, 'error': '产品不存在'})
                    continue

                # 创建订单
                order = Order(
                    order_no=order_no,
                    customer=customer,
                    order_date=datetime.now(),
                    product_id=product_id,
                    quantity=quantity,
                    note=note,
                    status='待备货'
                )
                db.session.add(order)
                # 刷新以获取order.id
                db.session.flush()

                # 订单增加库存
                product.current_stock += quantity
                log_order = InventoryLog(
                    product_id=product_id,
                    change_type='订单',
                    change_quantity=quantity,
                    related_id=order_no,
                    note=f'订单：{order_no}'
                )
                db.session.add(log_order)

                # 处理抵扣备货逻辑
                deduct_stock = order_data.get('deductStock') == 'on'
                custom_deduct_quantity = None

                # 解析自定义抵扣数量
                deductible_quantity = order_data.get('deductibleQuantity')
                if deductible_quantity:
                    with contextlib.suppress(ValueError, TypeError):
                        custom_deduct_quantity = int(deductible_quantity)

                # 调用抵扣函数
                if deduct_stock:
                    process_order_deduction(
                        order=order,
                        product_id=product_id,
                        order_quantity=quantity,
                        deduct_stock=True,
                        custom_deduct_quantity=custom_deduct_quantity
                    )

                success_count += 1

            except Exception as e:
                print(f"处理订单时出错: {e}")
                failed_orders.append({
                    'order': order_data,
                    'error': str(e)
                })
                continue

        # 提交事务
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'成功提交 {success_count} 个订单',
            'success_count': success_count,
            'failed_count': len(failed_orders),
            'failed_orders': failed_orders
        })

    except Exception as e:
        print(f"批量提交订单出错：{e}")
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': '批量提交失败',
            'error': str(e)
        })


# 批量导入订单
@csrf.exempt
@app.route('/batch-import-orders', methods=['POST'])
@api_permission_required('order_manage')
def batch_import_orders():
    """
    批量导入订单 - 支持统一导入模板
    统一模板格式: 客户名称, 产品名称, 订单数量, 抵扣备货, 备货数量, 备注
    """
    import shutil
    import tempfile

    from utils.batch_handler import batch_import_template
    from utils.excel_handler import excel_reader, parse_quantity, validate_required_field

    # 检查文件
    if 'file' not in request.files:
        return api_error('没有文件')

    file = request.files['file']

    # 保存文件到临时位置，以便多次读取
    temp_fd, temp_path = tempfile.mkstemp(suffix='.xlsx')
    try:
        file.save(temp_path)

        # 创建模拟文件对象
        class TempFile:
            def __init__(self, path, filename):
                self.path = path
                self.filename = filename

            def save(self, dest):
                shutil.copy(self.path, dest)

        temp_file = TempFile(temp_path, file.filename)

        # 先读取文件判断模板类型
        with excel_reader(temp_file) as reader:
            if reader.error:
                return api_error(reader.error)

            # 读取表头
            headers = []
            for col in range(1, 10):
                val = reader.get_cell_value(1, col)
                if val:
                    headers.append(str(val).strip())

            # 判断是否为统一导入模板（包含"抵扣备货"或"备货数量"列）
            is_unified_template = ('抵扣备货' in headers or '备货数量' in headers)

        # 重新创建文件对象用于导入
        temp_file = TempFile(temp_path, file.filename)

        if is_unified_template:
            # 统一导入模板格式: 客户名称, 产品名称, 订单数量, 抵扣备货, 备货数量, 备注
            def process_unified_order_row(row, get_cell_value):
                """处理统一导入模板的订单行"""
                from utils.batch_upload_utils import validate_customer_name, validate_product

                # 读取单元格数据
                customer = get_cell_value(row, 1)
                product_identifier = get_cell_value(row, 2)
                quantity = get_cell_value(row, 3)  # 订单数量
                deduct_flag = get_cell_value(row, 4)  # 抵扣备货
                # stockin_qty = get_cell_value(row, 5)  # 备货数量，订单导入不需要
                note = get_cell_value(row, 6)  # 备注

                # 如果订单数量为空，跳过此行（可能是备货行）
                if quantity is None or (isinstance(quantity, str) and quantity.strip() == ''):
                    return False, None

                # 验证必填字段
                valid, error = validate_required_field(customer, '客户名称', row)
                if not valid:
                    return False, error

                valid, error = validate_required_field(product_identifier, '产品名称', row)
                if not valid:
                    return False, error

                # 清理数据
                customer = str(customer).strip()
                product_identifier = str(product_identifier).strip()
                note = str(note).strip() if note else ''

                # 验证数量
                quantity, error = parse_quantity(quantity, '订单数量', row)
                if error:
                    return False, error

                # 验证客户名称
                is_valid, error_msg = validate_customer_name(customer)
                if not is_valid:
                    return False, f'第{row}行：{error_msg}'

                # 查找产品
                is_valid, product_id, error_msg = validate_product(product_identifier, db, Product)
                if not is_valid:
                    return False, f'第{row}行：{error_msg}'

                # 生成订单编号
                order_no = generate_order_number(db, Order)

                # 创建订单
                order = Order(
                    order_no=order_no,
                    customer=customer,
                    order_date=datetime.now(),
                    product_id=product_id,
                    quantity=quantity,
                    note=note,
                    status='待备货'
                )
                db.session.add(order)
                db.session.flush()

                # 添加库存日志
                log = InventoryLog(
                    product_id=product_id,
                    change_type='订单',
                    change_quantity=quantity,
                    related_id=order_no,
                    note=f'批量导入订单：{order_no}'
                )
                db.session.add(log)

                # 处理抵扣备货
                if deduct_flag and str(deduct_flag).strip() == '是':
                    process_order_deduction(order, product_id, quantity, deduct_stock=True)

                return True, None

            return batch_import_template(
                temp_file,
                ['客户名称', '产品名称', '订单数量', '抵扣备货', '备货数量', '备注'],
                process_unified_order_row,
                '订单',
                db
            )
        else:
            # 旧模板格式: 客户名称, 产品名称, 订单数量, 备注
            def process_order_row(row, get_cell_value):
                """处理单行订单数据"""
                from utils.batch_upload_utils import validate_customer_name, validate_product

                # 读取单元格数据
                customer = get_cell_value(row, 1)
                product_identifier = get_cell_value(row, 2)
                quantity = get_cell_value(row, 3)
                note = get_cell_value(row, 4)

                # 验证必填字段
                valid, error = validate_required_field(customer, '客户名称', row)
                if not valid:
                    return False, error

                valid, error = validate_required_field(product_identifier, '产品名称', row)
                if not valid:
                    return False, error

                # 清理数据
                customer = str(customer).strip()
                product_identifier = str(product_identifier).strip()
                note = str(note).strip() if note else ''

                # 验证数量
                quantity, error = parse_quantity(quantity, '订单数量', row)
                if error:
                    return False, error

                # 验证客户名称
                is_valid, error_msg = validate_customer_name(customer)
                if not is_valid:
                    return False, f'第{row}行：{error_msg}'

                # 查找产品
                is_valid, product_id, error_msg = validate_product(product_identifier, db, Product)
                if not is_valid:
                    return False, f'第{row}行：{error_msg}'

                # 生成订单编号
                order_no = generate_order_number(db, Order)

                # 创建订单
                order = Order(
                    order_no=order_no,
                    customer=customer,
                    order_date=datetime.now(),
                    product_id=product_id,
                    quantity=quantity,
                    note=note,
                    status='待备货'
                )
                db.session.add(order)
                db.session.flush()

                # 添加库存日志
                log = InventoryLog(
                    product_id=product_id,
                    change_type='订单',
                    change_quantity=quantity,
                    related_id=order_no,
                    note=f'批量导入订单：{order_no}'
                )
                db.session.add(log)

                return True, None

            return batch_import_template(
                temp_file,
                ['客户名称', '产品名称', '订单数量', '备注'],
                process_order_row,
                '订单',
                db
            )

    finally:
        # 清理临时文件
        import os
        try:
            os.close(temp_fd)
            os.unlink(temp_path)
        except:
            pass


# 批量导入备货
@csrf.exempt
@app.route('/batch-import-stockins', methods=['POST'])
@api_permission_required('stockin_manage')
def batch_import_stockins():
    """
    批量导入备货 - 支持统一导入模板
    统一模板格式: 客户名称, 产品名称, 订单数量, 抵扣备货, 备货数量, 备注
    """
    import shutil
    import tempfile

    from utils.batch_handler import batch_import_template
    from utils.excel_handler import ExcelReader, excel_reader, parse_quantity, validate_required_field

    # 检查文件
    if 'file' not in request.files:
        return api_error('没有文件')

    file = request.files['file']

    # 保存文件到临时位置，以便多次读取
    temp_fd, temp_path = tempfile.mkstemp(suffix='.xlsx')
    try:
        file.save(temp_path)

        # 创建模拟文件对象
        class TempFile:
            def __init__(self, path, filename):
                self.path = path
                self.filename = filename

            def save(self, dest):
                shutil.copy(self.path, dest)

        temp_file = TempFile(temp_path, file.filename)

        # 先读取文件判断模板类型
        with excel_reader(temp_file) as reader:
            if reader.error:
                return api_error(reader.error)

            # 读取表头
            headers = []
            for col in range(1, 10):
                val = reader.get_cell_value(1, col)
                if val:
                    headers.append(str(val).strip())

            # 判断是否为统一导入模板（包含"抵扣备货"或"备货数量"列）
            is_unified_template = ('抵扣备货' in headers or '备货数量' in headers)

        # 重新创建文件对象用于导入
        temp_file = TempFile(temp_path, file.filename)

        if is_unified_template:
            # 统一导入模板格式: 客户名称, 产品名称, 订单数量, 抵扣备货, 备货数量, 备注
            def process_unified_stockin_row(row, get_cell_value):
                """处理统一导入模板的备货行"""
                from utils.batch_upload_utils import validate_customer_name, validate_product

                # 读取单元格数据
                customer = get_cell_value(row, 1)
                product_identifier = get_cell_value(row, 2)
                # order_qty = get_cell_value(row, 3)  # 订单数量，备货导入不需要
                # deduct_flag = get_cell_value(row, 4)  # 抵扣备货，备货导入不需要
                quantity = get_cell_value(row, 5)  # 备货数量
                note = get_cell_value(row, 6)  # 备注

                # 如果备货数量为空，跳过此行（可能是订单行）
                if quantity is None or (isinstance(quantity, str) and quantity.strip() == ''):
                    return False, None

                # 验证必填字段
                valid, error = validate_required_field(customer, '客户名称', row)
                if not valid:
                    return False, error

                valid, error = validate_required_field(product_identifier, '产品名称', row)
                if not valid:
                    return False, error

                # 清理数据
                customer = str(customer).strip()
                product_identifier = str(product_identifier).strip()
                note = str(note).strip() if note else ''

                # 验证数量
                quantity, error = parse_quantity(quantity, '备货数量', row)
                if error:
                    return False, error

                # 验证客户名称
                is_valid, error_msg = validate_customer_name(customer)
                if not is_valid:
                    return False, f'第{row}行：{error_msg}'

                # 查找产品
                is_valid, product_id, error_msg = validate_product(product_identifier, db, Product)
                if not is_valid:
                    return False, f'第{row}行：{error_msg}'

                # 备货时间使用当前时间
                stockin_date = datetime.now()

                # 生成备货编号
                stockin_no = generate_stockin_number(db, StockIn)

                # 创建备货记录
                stockin = StockIn(
                    stockin_no=stockin_no,
                    stockin_date=stockin_date,
                    customer=customer,
                    product_id=product_id,
                    quantity=quantity,
                    note=note
                )
                db.session.add(stockin)

                # 备货操作增加产品库存
                product = Product.query.get(product_id)
                if product:
                    product.current_stock += quantity

                    # 添加库存日志
                    log = InventoryLog(
                        product_id=product_id,
                        change_type='备货',
                        change_quantity=quantity,
                        related_id=stockin_no,
                        note=f'批量导入备货：{stockin_no}'
                    )
                    db.session.add(log)

                return True, None

            return batch_import_template(
                temp_file,
                ['客户名称', '产品名称', '订单数量', '抵扣备货', '备货数量', '备注'],
                process_unified_stockin_row,
                '备货',
                db
            )
        else:
            # 旧模板格式: 客户名称, 产品名称, 备货数量, 备货时间, 备注
            def process_stockin_row(row, get_cell_value):
                """处理单行备货数据"""
                from utils.batch_upload_utils import validate_customer_name, validate_product

                # 读取单元格数据
                customer = get_cell_value(row, 1)
                product_identifier = get_cell_value(row, 2)
                quantity = get_cell_value(row, 3)
                stockin_date_val = get_cell_value(row, 4)
                note = get_cell_value(row, 5)

                # 验证必填字段
                valid, error = validate_required_field(customer, '客户名称', row)
                if not valid:
                    return False, error

                valid, error = validate_required_field(product_identifier, '产品名称', row)
                if not valid:
                    return False, error

                # 清理数据
                customer = str(customer).strip()
                product_identifier = str(product_identifier).strip()
                note = str(note).strip() if note else ''

                # 验证数量
                quantity, error = parse_quantity(quantity, '备货数量', row)
                if error:
                    return False, error

                # 验证客户名称
                is_valid, error_msg = validate_customer_name(customer)
                if not is_valid:
                    return False, f'第{row}行：{error_msg}'

                # 查找产品
                is_valid, product_id, error_msg = validate_product(product_identifier, db, Product)
                if not is_valid:
                    return False, f'第{row}行：{error_msg}'

                # 处理备货时间
                reader = ExcelReader(None)  # 仅用于日期解析
                stockin_date = reader.parse_date_value(stockin_date_val)

                # 生成备货编号
                stockin_no = generate_stockin_number(db, StockIn)

                # 创建备货记录
                stockin = StockIn(
                    stockin_no=stockin_no,
                    stockin_date=stockin_date,
                    customer=customer,
                    product_id=product_id,
                    quantity=quantity,
                    note=note
                )
                db.session.add(stockin)

                # 备货操作增加产品库存
                product = Product.query.get(product_id)
                if product:
                    product.current_stock += quantity

                    # 添加库存日志
                    log = InventoryLog(
                        product_id=product_id,
                        change_type='备货',
                        change_quantity=quantity,
                        related_id=stockin_no,
                        note=f'批量导入备货：{stockin_no}'
                    )
                    db.session.add(log)

                return True, None

            return batch_import_template(
                temp_file,
                ['客户名称', '产品名称', '备货数量', '备货时间', '备注'],
                process_stockin_row,
                '备货',
                db
            )

    finally:
        # 清理临时文件
        import os
        try:
            os.close(temp_fd)
            os.unlink(temp_path)
        except:
            pass


# 统一导入（产品、订单、备货）
@csrf.exempt
@app.route('/batch-import-unified', methods=['POST'])
@api_permission_required('product_manage')
def batch_import_unified():
    """
    统一导入 - 支持产品、订单、备货三种类型的统一导入
    使用统一导入模板，通过"导入类型"字段区分不同业务
    """
    from utils.batch_handler import batch_import_unified_template
    from utils.batch_upload_utils import validate_customer_name, validate_product
    from utils.excel_handler import ExcelReader, parse_quantity, validate_required_field

    def process_unified_row(import_type, row, reader, Product, Order, StockIn, InventoryLog, db):
        """处理统一导入的单行数据"""

        # 读取公共字段
        customer = reader.get_cell_value(row, 2)
        product_name = reader.get_cell_value(row, 3)
        barcode = reader.get_cell_value(row, 4)
        quantity = reader.get_cell_value(row, 5)
        time_val = reader.get_cell_value(row, 6)
        deduct_flag = reader.get_cell_value(row, 7)
        note = reader.get_cell_value(row, 8)

        if import_type == 'product':
            # ===== 产品导入 =====
            # 验证必填字段
            valid, error = validate_required_field(product_name, '产品名称', row)
            if not valid:
                return False, error

            # 清理数据
            name = str(product_name).strip()
            barcode_val = str(barcode).strip() if barcode else ''
            note_val = str(note).strip() if note else ''

            # 验证库存数据
            if quantity is None:
                initial_stock = 0
            else:
                try:
                    if isinstance(quantity, str):
                        quantity = quantity.strip()
                        initial_stock = 0 if quantity == '' else int(float(quantity))
                    elif isinstance(quantity, float):
                        initial_stock = int(quantity)
                    else:
                        initial_stock = int(quantity)

                    if initial_stock < 0:
                        initial_stock = 0
                except (ValueError, TypeError):
                    return False, f'第{row}行：初始库存必须是数字，实际值：{quantity}'

            # 检查是否已存在
            existing = Product.query.filter_by(name=name).first()
            if existing:
                return False, None  # 跳过已存在的产品

            # 创建产品
            product = Product(
                name=name,
                barcode=barcode_val,
                initial_stock=initial_stock,
                current_stock=initial_stock
            )
            db.session.add(product)
            db.session.flush()

            # 添加库存日志
            log = InventoryLog(
                product_id=product.id,
                change_type='初始库存',
                change_quantity=initial_stock,
                related_id=str(product.id),
                note=f'统一导入: {note_val}'
            )
            db.session.add(log)

            return True, None

        elif import_type == 'order':
            # ===== 订单导入 =====
            # 验证必填字段
            valid, error = validate_required_field(customer, '客户名称', row)
            if not valid:
                return False, error

            valid, error = validate_required_field(product_name, '产品名称', row)
            if not valid:
                return False, error

            # 清理数据
            customer_val = str(customer).strip()
            product_identifier = str(product_name).strip()
            note_val = str(note).strip() if note else ''

            # 验证数量
            quantity_val, error = parse_quantity(quantity, '订单数量', row)
            if error:
                return False, error

            # 验证客户名称
            is_valid, error_msg = validate_customer_name(customer_val)
            if not is_valid:
                return False, f'第{row}行：{error_msg}'

            # 查找产品
            is_valid, product_id, error_msg = validate_product(product_identifier, db)
            if not is_valid:
                return False, f'第{row}行：{error_msg}'

            # 生成订单编号
            order_no = generate_order_number(db, Order)

            # 创建订单（订单时间自动使用当前北京时间）
            order = Order(
                order_no=order_no,
                customer=customer_val,
                order_date=datetime.now(),  # 自动使用当前北京时间
                product_id=product_id,
                quantity=quantity_val,
                note=note_val,
                status='待备货'
            )
            db.session.add(order)
            db.session.flush()

            # 添加库存日志
            log = InventoryLog(
                product_id=product_id,
                change_type='订单',
                change_quantity=quantity_val,
                related_id=order_no,
                note=f'统一导入订单：{order_no}'
            )
            db.session.add(log)

            # 处理抵扣备货
            if deduct_flag and str(deduct_flag).strip() == '是':
                process_order_deduction(order, product_id, quantity_val, deduct_stock=True)

            return True, None

        elif import_type == 'stockin':
            # ===== 备货导入 =====
            # 验证必填字段
            valid, error = validate_required_field(customer, '客户名称', row)
            if not valid:
                return False, error

            valid, error = validate_required_field(product_name, '产品名称', row)
            if not valid:
                return False, error

            # 清理数据
            customer_val = str(customer).strip()
            product_identifier = str(product_name).strip()
            note_val = str(note).strip() if note else ''

            # 验证数量
            quantity_val, error = parse_quantity(quantity, '备货数量', row)
            if error:
                return False, error

            # 验证客户名称
            is_valid, error_msg = validate_customer_name(customer_val)
            if not is_valid:
                return False, f'第{row}行：{error_msg}'

            # 查找产品
            is_valid, product_id, error_msg = validate_product(product_identifier, db)
            if not is_valid:
                return False, f'第{row}行：{error_msg}'

            # 处理备货时间（如果为空则自动使用当前北京时间）
            reader_obj = ExcelReader(None)
            stockin_date = reader_obj.parse_date_value(time_val) if time_val else datetime.now()

            # 生成备货编号
            stockin_no = generate_stockin_number(db, StockIn)

            # 创建备货记录
            stockin = StockIn(
                stockin_no=stockin_no,
                stockin_date=stockin_date,
                customer=customer_val,
                product_id=product_id,
                quantity=quantity_val,
                note=note_val
            )
            db.session.add(stockin)

            # 备货操作增加产品库存
            product = Product.query.get(product_id)
            if product:
                product.current_stock += quantity_val

                # 添加库存日志
                log = InventoryLog(
                    product_id=product_id,
                    change_type='备货',
                    change_quantity=quantity_val,
                    related_id=stockin_no,
                    note=f'统一导入备货：{stockin_no}'
                )
                db.session.add(log)

            return True, None

        return False, f'第{row}行：未知的导入类型'

    # 检查文件
    if 'file' not in request.files:
        return api_error('没有文件')

    file = request.files['file']

    # 使用统一导入模板
    models = {
        'Product': Product,
        'Order': Order,
        'StockIn': StockIn,
        'InventoryLog': InventoryLog
    }

    return batch_import_unified_template(file, db, models, process_unified_row)


# 批量提交备货 API
@app.route('/api/batch-submit-stockins', methods=['POST'])
@csrf.exempt
@api_permission_required('stockin_manage')
def batch_submit_stockins():
    """
    批量提交备货API，返回JSON响应而不是重定向
    """
    try:
        data = request.get_json()
        stockins_data = data.get('stockins', [])

        if not stockins_data:
            return jsonify({
                'success': False,
                'message': '没有备货数据'
            })

        success_count = 0
        failed_stockins = []

        for stockin_data in stockins_data:
            try:
                # 生成备货编号
                stockin_no = generate_stockin_number(db, StockIn)

                # 验证必填字段
                product_id_str = str(stockin_data.get('productId', '')).strip()
                quantity_str = str(stockin_data.get('quantity', '')).strip()
                stockin_date_str = stockin_data.get('stockinDate', '')

                if not product_id_str:
                    failed_stockins.append({
                        'stockin': stockin_data,
                        'error': '请选择产品'
                    })
                    continue

                if not quantity_str or quantity_str == '0':
                    failed_stockins.append({
                        'stockin': stockin_data,
                        'error': '请输入有效的数量'
                    })
                    continue

                if not stockin_date_str:
                    failed_stockins.append({
                        'stockin': stockin_data,
                        'error': '请选择备货时间'
                    })
                    continue

                try:
                    product_id = int(product_id_str)
                    quantity = int(quantity_str)
                    stockin_date = datetime.strptime(stockin_date_str, '%Y-%m-%d')
                except ValueError:
                    failed_stockins.append({
                        'stockin': stockin_data,
                        'error': '数据格式错误'
                    })
                    continue

                # 检查产品是否存在
                product = Product.query.get(product_id)
                if not product:
                    failed_stockins.append({
                        'stockin': stockin_data,
                        'error': '产品不存在'
                    })
                    continue

                # 检查数量是否为正整数
                if quantity <= 0:
                    failed_stockins.append({
                        'stockin': stockin_data,
                        'error': '数量必须大于0'
                    })
                    continue

                # 创建备货记录
                note = stockin_data.get('note', '')
                customer = stockin_data.get('customer', '')

                stockin = StockIn(
                    stockin_no=stockin_no,
                    stockin_date=stockin_date,
                    customer=customer,
                    product_id=product_id,
                    quantity=quantity,
                    note=note
                )
                db.session.add(stockin)

                # 备货操作增加产品库存
                product.current_stock += quantity

                # 添加库存日志
                log = InventoryLog(
                    product_id=product_id,
                    change_type='备货',
                    change_quantity=quantity,
                    related_id=stockin_no,
                    note=f'备货：{stockin_no}'
                )
                db.session.add(log)

                success_count += 1

            except Exception as e:
                print(f"处理备货时出错: {e}")
                failed_stockins.append({
                    'stockin': stockin_data,
                    'error': str(e)
                })

        # 提交事务
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'成功提交 {success_count} 个备货',
            'success_count': success_count,
            'failed_count': len(failed_stockins),
            'failed_stockins': failed_stockins
        })

    except Exception as e:
        print(f"批量提交备货出错: {e}")
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': '批量提交失败',
            'error': str(e)
        })

# 批量提交出货API
@app.route('/api/batch-submit-stockouts', methods=['POST'])
@csrf.exempt
@api_permission_required('stockout_manage')
def batch_submit_stockouts():
    """
    批量提交出货API，返回JSON响应而不是重定向
    """
    try:
        data = request.get_json()
        stockouts_data = data.get('stockouts', [])

        if not stockouts_data:
            return jsonify({
                'success': False,
                'message': '没有出货数据'
            })

        success_count = 0
        failed_stockouts = []

        for stockout_data in stockouts_data:
            try:
                # 生成出货编号
                stockout_no = generate_stockout_number(db, StockOut)

                # 验证必填字段
                customer = stockout_data.get('customer', '')
                product_id_str = str(stockout_data.get('productId', '')).strip()
                quantity_str = str(stockout_data.get('quantity', '')).strip()
                stockout_date_str = stockout_data.get('stockoutDate', '')

                if not customer:
                    failed_stockouts.append({
                        'stockout': stockout_data,
                        'error': '请选择客户'
                    })
                    continue

                if not product_id_str:
                    failed_stockouts.append({
                        'stockout': stockout_data,
                        'error': '请选择产品'
                    })
                    continue

                if not quantity_str or quantity_str == '0':
                    failed_stockouts.append({
                        'stockout': stockout_data,
                        'error': '请输入有效的数量'
                    })
                    continue

                if not stockout_date_str:
                    failed_stockouts.append({
                        'stockout': stockout_data,
                        'error': '请选择出货时间'
                    })
                    continue

                try:
                    product_id = int(product_id_str)
                    quantity = int(quantity_str)
                    stockout_date = datetime.strptime(stockout_date_str, '%Y-%m-%d')
                except ValueError:
                    failed_stockouts.append({
                        'stockout': stockout_data,
                        'error': '数据格式错误'
                    })
                    continue

                # 检查产品是否存在
                product = Product.query.get(product_id)
                if not product:
                    failed_stockouts.append({
                        'stockout': stockout_data,
                        'error': '产品不存在'
                    })
                    continue

                if product.current_stock < quantity:
                    failed_stockouts.append({
                        'stockout': stockout_data,
                        'error': '库存不足'
                    })
                    continue

                # 创建出货记录
                note = stockout_data.get('note', '')

                stockout = StockOut(
                    stockout_no=stockout_no,
                    stockout_date=stockout_date,
                    product_id=product_id,
                    quantity=quantity,
                    customer=customer,
                    note=note
                )
                db.session.add(stockout)

                # 更新产品库存
                product.current_stock -= quantity

                # 添加库存日志
                log = InventoryLog(
                    product_id=product_id,
                    change_type='出货',
                    change_quantity=-quantity,
                    related_id=stockout_no,
                    note=f'出货：{stockout_no}',
                    customer=customer
                )
                db.session.add(log)

                success_count += 1

            except Exception as e:
                print(f"处理出货时出错: {e}")
                failed_stockouts.append({
                    'stockout': stockout_data,
                    'error': str(e)
                })

        # 提交事务
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'成功提交 {success_count} 个出货',
            'success_count': success_count,
            'failed_count': len(failed_stockouts),
            'failed_stockouts': failed_stockouts
        })

    except Exception as e:
        print(f"批量提交出货出错: {e}")
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': '批量提交失败',
            'error': str(e)
        })

# 产品搜索API
@csrf.exempt
@app.route('/api/product-search')
@api_permission_required('order_manage')
def product_search():
    query = request.args.get('q', '')
    if query:
        products = Product.query.filter(Product.name.contains(query)).all()
    else:
        products = Product.query.limit(20).all()
    result = []
    for p in products:
        result.append({
            'id': p.id,
            'name': p.name,
            'barcode': p.barcode or '',
            'current_stock': p.current_stock
        })
    return jsonify(result)

# 获取可用备货列表API
@csrf.exempt
@app.route('/api/available-stockins')
@api_permission_required('order_manage')
def available_stockins():
    product_id = request.args.get('product_id', type=int)
    request.args.get('order_quantity', 1, type=int)

    query = StockIn.query.filter(StockIn.quantity > 0)

    if product_id:
        query = query.filter(StockIn.product_id == product_id)

    stockins = query.all()
    result = []

    for stockin in stockins:
        try:
            result.append({
                'id': stockin.id,
                'stockin_no': stockin.stockin_no,
                'product_id': stockin.product_id,
                'product_name': stockin.product.name,
                'quantity': stockin.quantity
            })
        except Exception as e:
            print(f"处理备货 {stockin.stockin_no} 时出错: {e}")

    result.sort(key=lambda x: x['quantity'], reverse=True)

    return jsonify(result)

# 获取备货详情API
@csrf.exempt
@app.route('/api/stockin-info/<int:stockin_id>')
@api_permission_required('order_manage')
def stockin_info(stockin_id):
    stockin = StockIn.query.get_or_404(stockin_id)
    return jsonify({
        'id': stockin.id,
        'stockin_no': stockin.stockin_no,
        'product_id': stockin.product_id,
        'product_name': stockin.product.name,
        'quantity': stockin.quantity
    })

# 获取产品可用备货库存API
@csrf.exempt
@app.route('/api/product-available-stock')
@api_permission_required('order_manage')
def product_available_stock():
    product_id = request.args.get('product_id', type=int)

    if not product_id:
        return jsonify({
            'available_stock': 0,
            'message': '请指定产品'
        })

    stockins = StockIn.query.filter_by(product_id=product_id).all()
    total_quantity = sum(s.quantity for s in stockins)

    return jsonify({
        'available_stock': total_quantity,
        'product_id': product_id
    })

# 库存校验API
@csrf.exempt
@app.route('/api/validate-deduct-quantity', methods=['POST'])
@api_permission_required('order_manage')
def validate_deduct_quantity():
    try:
        data = request.get_json()
        product_id = data.get('product_id')
        deduct_quantity = data.get('deduct_quantity', 0)
        order_quantity = data.get('order_quantity', 0)

        if not product_id:
            return jsonify({
                'valid': False,
                'message': '请选择产品',
                'available_stock': 0
            })

        stockins = StockIn.query.filter_by(product_id=product_id).all()
        total_quantity = sum(s.quantity for s in stockins)

        if deduct_quantity < 0:
            return jsonify({
                'valid': False,
                'message': '抵扣数量不能为负数',
                'available_stock': total_quantity
            })

        if deduct_quantity > total_quantity:
            return jsonify({
                'valid': False,
                'message': f'抵扣数量不能超过备货总库存（当前可用 {total_quantity}）',
                'available_stock': total_quantity
            })

        if deduct_quantity > order_quantity:
            return jsonify({
                'valid': False,
                'message': f'抵扣数量不能超过订单总数量（订单数量 {order_quantity}）',
                'available_stock': total_quantity
            })

        return jsonify({
            'valid': True,
            'message': '校验通过',
            'available_stock': total_quantity
        })
    except Exception as e:
        _agent_log("H1", "validate_deduct:error", "Failed to validate deduct quantity", {"error": str(e)})
        return jsonify({
            'valid': False,
            'message': f'校验失败: {str(e)}',
            'available_stock': 0
        })

# 操作日志API
@csrf.exempt
@app.route('/api/log-operation', methods=['POST'])
@api_permission_required('order_manage')
def log_operation():
    try:
        data = request.get_json()

        if not data:
            return jsonify({'success': False, 'message': '无效的请求数据'})

        log_type = data.get('type', '')
        log_data = data.get('data', {})
        timestamp = data.get('timestamp', '')

        # 记录到日志
        _agent_log("H1", f"operation_log:{log_type}", "Operation logged", {
            "type": log_type,
            "data": log_data,
            "timestamp": timestamp
        })

        return jsonify({'success': True, 'message': '日志记录成功'})
    except Exception as e:
        _agent_log("H1", "operation_log:error", "Failed to log operation", {"error": str(e)})
        return jsonify({'success': False, 'message': f'记录日志失败: {str(e)}'})

# 确认备货抵扣API（原子性操作）
@csrf.exempt
@app.route('/api/confirm-stockin-deduction', methods=['POST'])
@api_permission_required('order_manage')
def confirm_stockin_deduction():
    data = request.get_json()
    stockins = data.get('stockins', [])

    if not stockins:
        return jsonify({'success': False, 'message': '请选择备货SKU'})

    # 验证参数完整性
    for item in stockins:
        if not all(key in item for key in ['id', 'quantity', 'stockin_no', 'product_name']):
            return jsonify({'success': False, 'message': '备货数据不完整'})

    # 使用数据库事务确保原子性
    try:
        # 第一阶段：预验证所有备货的可用性
        stockin_objects = []
        total_deducted = 0

        for item in stockins:
            stockin = StockIn.query.get(item['id'])
            if not stockin:
                return jsonify({'success': False, 'message': f"备货 {item['stockin_no']} 不存在"})

            quantity = item['quantity']
            if quantity <= 0:
                return jsonify({'success': False, 'message': f"备货 {item['stockin_no']} 的抵扣数量必须大于0"})

            if quantity > stockin.quantity:
                return jsonify({'success': False, 'message': f"备货 {item['stockin_no']} 的数量不足，当前数量：{stockin.quantity}"})

            stockin_objects.append((stockin, quantity))
            total_deducted += quantity

        # 第二阶段：执行所有抵扣操作
        stockout_records = []

        for stockin, quantity in stockin_objects:
            # 创建出货记录
            stockout_no = f'STK-OUT-{datetime.now().strftime("%Y%m%d%H%M%S%f")}'
            stockout = StockOut(
                stockout_no=stockout_no,
                stockout_date=datetime.now(),
                product_id=stockin.product_id,
                quantity=quantity,
                customer=stockin.customer,  # 添加客户信息
                order_id=None,  # 订单创建后再关联
                stockin_id=stockin.id,
                note=f'订单预抵扣：{stockin.stockin_no}'
            )
            db.session.add(stockout)
            stockout_records.append(stockout_no)

            # 更新产品库存
            stockin.product.current_stock -= quantity

            # 添加库存日志
            log = InventoryLog(
                product_id=stockin.product_id,
                change_type='订单抵扣',
                change_quantity=-quantity,
                related_id=stockout_no,
                note=f'订单抵扣：{stockin.stockin_no}，数量：{quantity}'
            )
            db.session.add(log)

        # 提交事务
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'备货抵扣成功，总计抵扣数量：{total_deducted}',
            'total_deducted': total_deducted,
            'stockout_records': stockout_records
        })

    except Exception as e:
        # 事务回滚，确保数据一致性
        db.session.rollback()
        import traceback
        print(f"备货抵扣失败：{e}")
        print(traceback.format_exc())
        return jsonify({'success': False, 'message': f'备货抵扣失败：{str(e)}'})

@app.route('/order/edit/<int:id>', methods=['GET', 'POST'])
@api_permission_required('order_manage')
def edit_order(id):
    order = Order.query.get_or_404(id)
    if request.method == 'POST':
        order.customer = request.form['customer']
        order.product_id = int(request.form['product_id'])
        new_quantity = int(request.form['quantity'])
        order.note = request.form['note']
        order.order_date = datetime.strptime(request.form['order_date'], '%Y-%m-%d') if request.form['order_date'] else datetime.now()
        # 已备货/已出货订单不能修改数量
        if order.status in ['已备货', '已出货']:
            flash('已备货或已出货的订单不能修改数量！', 'error')
            return redirect(url_for('orders'))
        # 调整订单数量
        quantity_change = new_quantity - order.quantity
        order.quantity = new_quantity
        if quantity_change != 0:
            product = order.product
            product.current_stock += quantity_change
            # 添加库存日志
            log = InventoryLog(
                product_id=product.id,
                change_type='修改订单',
                change_quantity=quantity_change,
                related_id=order.order_no,
                note=f'修改订单：{order.order_no}'
            )
            db.session.add(log)
        db.session.commit()
        flash('订单编辑成功！', 'success')
        return redirect(url_for('orders'))
    products = Product.query.all()
    return render_template('edit_order.html', order=order, products=products)

@app.route('/order/delete/<int:id>')
@api_permission_required('order_manage')
def delete_order(id):
    order = Order.query.get_or_404(id)
    # 已备货/已出货订单不能删除
    if order.status in ['已备货', '已出货']:
        flash('已备货或已出货的订单不能删除！', 'error')
        return redirect(url_for('orders'))

    # 先删除关联的出货记录，并恢复订单抵扣的库存
    if order.stockouts:
        for stockout in order.stockouts:
            # 恢复订单抵扣的库存
            product = stockout.product
            product.current_stock += stockout.quantity
            # 添加恢复库存的日志
            log_restore = InventoryLog(
                product_id=product.id,
                change_type='恢复订单抵扣',
                change_quantity=stockout.quantity,
                related_id=stockout.stockout_no,
                note=f'删除订单恢复订单抵扣：{stockout.stockout_no}'
            )
            db.session.add(log_restore)
            db.session.delete(stockout)

    # 删除订单时减少库存（恢复订单创建时增加的库存）
    product = order.product
    product.current_stock -= order.quantity
    # 添加删除订单的库存日志
    log = InventoryLog(
        product_id=product.id,
        change_type='删除订单',
        change_quantity=-order.quantity,
        related_id=order.order_no,
        note=f'删除订单：{order.order_no}'
    )
    db.session.add(log)

    # 删除订单
    db.session.delete(order)
    db.session.commit()
    flash('订单删除成功！', 'success')
    return redirect(url_for('orders'))

# 备货管理
@app.route('/stockins', methods=['GET', 'POST'])
@api_permission_required('stockin_manage')
def stockins():
    if request.method == 'POST':
        # 自动生成备货编号
        stockin_no = generate_stockin_number(db, StockIn)
        customer = request.form['customer']
        product_id = int(request.form['product_id'])
        quantity = int(request.form['quantity'])
        note = request.form['note']
        stockin_date = datetime.strptime(request.form['stockin_date'], '%Y-%m-%d') if request.form['stockin_date'] else datetime.now()

        # 检查产品是否存在
        product = Product.query.get(product_id)
        if not product:
            flash('产品不存在！', 'error')
            return redirect(url_for('stockins'))
        # 创建备货记录
        stockin = StockIn(stockin_no=stockin_no, stockin_date=stockin_date, customer=customer, product_id=product_id, quantity=quantity, note=note)
        db.session.add(stockin)
        # 备货操作增加产品库存
        product.current_stock += quantity
        # 添加库存日志
        log = InventoryLog(product_id=product_id, change_type='备货', change_quantity=quantity, related_id=stockin_no, note=f'备货：{stockin_no}')
        db.session.add(log)
        db.session.commit()
        flash(f'备货添加成功！备货编号：{stockin_no}', 'success')
        return redirect(url_for('stockins'))

    # 使用 joinedload 预加载 stockouts 关联数据，避免 N+1 查询
    from collections import OrderedDict

    from sqlalchemy.orm import joinedload

    # 查询所有备货记录，预加载产品和 stockouts 关联数据
    stockins = StockIn.query.options(
        joinedload(StockIn.product),
        joinedload(StockIn.stockouts).joinedload(StockOut.order)
    ).all()

    # 按客户 + 产品分组
    grouped_stockins = OrderedDict()
    for stockin in stockins:
        # 分组键：客户名称 + 产品 ID
        key = (stockin.customer, stockin.product_id)

        if key not in grouped_stockins:
            grouped_stockins[key] = {
                'customer': stockin.customer,
                'product': stockin.product,
                'product_id': stockin.product_id,
                'total_quantity': 0,
                'total_deducted': 0,
                'earliest_date': stockin.stockin_date,
                'note': stockin.note,
                'original_records': []
            }

        # 累加数量
        grouped_stockins[key]['total_quantity'] += stockin.quantity

        # 累加已抵扣数量（通过 stockouts 关联）
        if stockin.stockouts:
            for stockout in stockin.stockouts:
                grouped_stockins[key]['total_deducted'] += stockout.quantity

        # 更新最早时间（如果当前记录更早）
        if stockin.stockin_date < grouped_stockins[key]['earliest_date']:
            grouped_stockins[key]['earliest_date'] = stockin.stockin_date
            grouped_stockins[key]['note'] = stockin.note

        # 添加原始记录到列表
        grouped_stockins[key]['original_records'].append(stockin)

    products = Product.query.all()
    preview_stockin_no = generate_stockin_number(db, StockIn)

    # 将分组数据转换为列表格式，供前端按日期分组
    stockins_list = []
    for key, group in grouped_stockins.items():
        for record in group['original_records']:
            stockins_list.append({
                'id': record.id,
                'stockin_no': record.stockin_no,
                'stockin_date': record.stockin_date.strftime('%Y-%m-%d') if record.stockin_date else '',
                'customer': record.customer,
                'product': {
                    'id': record.product.id,
                    'name': record.product.name,
                    'barcode': record.product.barcode,
                    'image': record.product.image
                },
                'quantity': record.quantity,
                'deducted': sum(s.quantity for s in record.stockouts) if record.stockouts else 0,
                'note': record.note
            })

    return render_template('stockin.html',
                         grouped_stockins=grouped_stockins,
                         stockins_json=stockins_list,
                         products=products,
                         preview_stockin_no=preview_stockin_no)

# 编辑备货记录
@app.route('/edit-stockin/<int:id>', methods=['GET', 'POST'])
@api_permission_required('stockin_manage')
def edit_stockin(id):
    stockin = StockIn.query.get_or_404(id)
    if request.method == 'POST':
        stockin_no = request.form['stockin_no']
        customer = request.form['customer']
        product_id = int(request.form['product_id'])
        quantity = int(request.form['quantity'])
        note = request.form['note']
        stockin_date = datetime.strptime(request.form['stockin_date'], '%Y-%m-%d') if request.form['stockin_date'] else datetime.now()

        # 检查备货编号是否已存在（排除当前记录）
        existing_stockin = StockIn.query.filter(StockIn.stockin_no == stockin_no, StockIn.id != id).first()
        if existing_stockin:
            flash('备货编号已存在！', 'error')
            return redirect(url_for('edit_stockin', id=id))

        # 检查产品是否存在
        product = Product.query.get(product_id)
        if not product:
            flash('产品不存在！', 'error')
            return redirect(url_for('edit_stockin', id=id))

        # 计算库存变化
        quantity_change = quantity - stockin.quantity

        # 更新备货记录
        stockin.stockin_no = stockin_no
        stockin.stockin_date = stockin_date
        stockin.customer = customer
        stockin.product_id = product_id
        stockin.quantity = quantity
        stockin.note = note

        # 更新产品库存
        product.current_stock += quantity_change

        # 添加库存日志
        log = InventoryLog(product_id=product_id, change_type='备货调整', change_quantity=quantity_change, related_id=stockin_no, note=f'调整备货：{stockin_no}')
        db.session.add(log)

        db.session.commit()
        flash('备货修改成功！', 'success')
        return redirect(url_for('stockins'))

    products = Product.query.all()
    return render_template('edit_stockin.html', stockin=stockin, products=products)

# 编辑出货记录
@app.route('/edit-stockout/<int:id>', methods=['GET', 'POST'])
@permission_required('stockout_manage')
def edit_stockout(id):
    stockout = StockOut.query.get_or_404(id)
    if request.method == 'POST':
        stockout_no = request.form['stockout_no']
        customer = request.form['customer']
        product_id = int(request.form['product_id'])
        quantity = int(request.form['quantity'])
        note = request.form['note']
        stockout_date = datetime.strptime(request.form['stockout_date'], '%Y-%m-%d') if request.form['stockout_date'] else datetime.now()

        # 检查出货编号是否已存在（排除当前记录）
        existing_stockout = StockOut.query.filter(StockOut.stockout_no == stockout_no, StockOut.id != id).first()
        if existing_stockout:
            flash('出货编号已存在！', 'error')
            return redirect(url_for('edit_stockout', id=id))

        # 检查产品是否存在
        product = Product.query.get(product_id)
        if not product:
            flash('产品不存在！', 'error')
            return redirect(url_for('edit_stockout', id=id))

        # 计算库存变化
        quantity_change = quantity - stockout.quantity

        # 检查库存是否足够（如果数量增加）
        if quantity_change > 0 and product.current_stock < quantity_change:
            flash('库存不足，无法增加出货数量！', 'error')
            return redirect(url_for('edit_stockout', id=id))

        # 更新出货记录
        stockout.stockout_no = stockout_no
        stockout.stockout_date = stockout_date
        stockout.customer = customer
        stockout.product_id = product_id
        stockout.quantity = quantity
        stockout.note = note

        # 更新产品库存
        product.current_stock -= quantity_change

        # 添加库存日志
        log = InventoryLog(
            product_id=product_id,
            change_type='出货调整',
            change_quantity=-quantity_change,
            related_id=stockout_no,
            note=f'调整出货：{stockout_no}'
        )
        db.session.add(log)

        db.session.commit()
        flash('出货修改成功！', 'success')
        return redirect(url_for('stockouts'))

    products = Product.query.all()
    return render_template('edit_stockout.html', stockout=stockout, products=products)

# 删除出货记录
@app.route('/delete-stockout/<int:id>')
@permission_required('stockout_manage')
def delete_stockout(id):
    stockout = StockOut.query.get_or_404(id)

    # 保存产品信息
    product = stockout.product
    quantity = stockout.quantity
    stockout_no = stockout.stockout_no

    # 删除出货记录
    db.session.delete(stockout)
    # 恢复产品库存
    product.current_stock += quantity
    # 添加库存日志
    log = InventoryLog(
        product_id=product.id,
        change_type='删除出货',
        change_quantity=quantity,
        related_id=stockout_no,
        note=f'删除出货：{stockout_no}'
    )
    db.session.add(log)
    db.session.commit()
    flash('出货删除成功！', 'success')
    return redirect(url_for('stockouts'))

# 删除备货记录
@app.route('/delete-stockin/<int:id>')
@api_permission_required('stockin_manage')
def delete_stockin(id):
    stockin = StockIn.query.get_or_404(id)

    # 检查是否有出货记录
    if stockin.stockouts:
        flash('该备货已有出货记录，无法删除！', 'error')
        return redirect(url_for('stockins'))

    # 保存产品信息
    product = stockin.product
    quantity = stockin.quantity
    stockin_no = stockin.stockin_no

    # 删除备货记录
    db.session.delete(stockin)
    # 减少产品库存
    product.current_stock -= quantity
    # 添加库存日志
    log = InventoryLog(product_id=product.id, change_type='删除备货', change_quantity=-quantity, related_id=stockin_no, note=f'删除备货：{stockin_no}')
    db.session.add(log)
    db.session.commit()
    flash('备货删除成功！', 'success')
    return redirect(url_for('stockins'))

# 出货管理
@app.route('/stockouts', methods=['GET', 'POST'])
@permission_required('stockout_manage')
def stockouts():
    if request.method == 'POST':
        # 自动生成出货编号
        stockout_no = generate_stockout_number(db, StockOut)
        customer = request.form['customer']
        product_id = int(request.form['product_id'])
        quantity = int(request.form['quantity'])
        note = request.form['note']
        stockout_date = datetime.strptime(request.form['stockout_date'], '%Y-%m-%d') if request.form['stockout_date'] else datetime.now()

        # 检查产品是否存在
        product = Product.query.get(product_id)
        if not product:
            flash('产品不存在！', 'error')
            return redirect(url_for('stockouts'))

        # 检查产品库存
        if product.current_stock < quantity:
            flash('库存不足！', 'error')
            return redirect(url_for('stockouts'))

        # 创建出货记录
        stockout = StockOut(stockout_no=stockout_no, stockout_date=stockout_date, product_id=product_id, quantity=quantity, customer=customer, note=note)
        db.session.add(stockout)
        # 更新产品库存
        product.current_stock -= quantity
        # 添加库存日志
        log = InventoryLog(product_id=product.id, change_type='出货', change_quantity=-quantity, related_id=stockout_no, note=f'出货：{stockout_no}', customer=customer)
        db.session.add(log)
        db.session.commit()
        flash(f'出货添加成功！出货编号：{stockout_no}', 'success')
        return redirect(url_for('stockouts'))
    # 过滤掉订单抵扣的记录，只显示真正的出货记录
    # 订单抵扣的记录note以'[订单抵扣]'开头
    # 使用joinedload预加载关联对象,避免N+1查询问题
    stockouts = StockOut.query\
        .options(joinedload(StockOut.product))\
        .options(joinedload(StockOut.order))\
        .options(joinedload(StockOut.stockin))\
        .filter(~StockOut.note.like('[订单抵扣]%'))\
        .all()

    # 转换为列表格式，供前端按日期分组
    stockouts_list = []
    for stockout in stockouts:
        stockouts_list.append({
            'id': stockout.id,
            'stockout_no': stockout.stockout_no,
            'stockout_date': stockout.stockout_date.strftime('%Y-%m-%d') if stockout.stockout_date else '',
            'customer': stockout.customer,
            'product': {
                'id': stockout.product.id,
                'name': stockout.product.name,
                'barcode': stockout.product.barcode,
                'image': stockout.product.image
            },
            'quantity': stockout.quantity,
            'note': stockout.note
        })

    preview_stockout_no = generate_stockout_number(db, StockOut)
    return render_template('stockout.html', stockouts=stockouts, stockouts_json=stockouts_list, preview_stockout_no=preview_stockout_no)

# 库存查询
@app.route('/inventory')
@api_permission_required('inventory_view')
def inventory():
    # 获取查询参数
    search_customer = request.args.get('customer', '').strip()
    search_product = request.args.get('product', '').strip()

    # 获取所有订单和备货数据，按客户和产品分组
    # 订单数量保持原始总量（不扣除抵扣）
    order_groups = db.session.query(
        Order.customer,
        Order.product_id,
        func.sum(Order.quantity).label('order_quantity')
    ).filter(Order.status != '已取消')

    if search_customer:
        order_groups = order_groups.filter(Order.customer.ilike(f'%{search_customer}%'))

    order_groups = order_groups.group_by(Order.customer, Order.product_id).all()

    # 创建数据字典
    order_data = {(g.customer, g.product_id): g.order_quantity for g in order_groups}

    # 重新组织查询逻辑，更简单的方式：
    # 直接查询所有 StockIn，并计算每个 (customer, product_id) 的总备货和总抵扣
    # 使用joinedload预加载关联对象,避免N+1查询问题
    stockins = StockIn.query\
        .options(joinedload(StockIn.product))\
        .options(selectinload(StockIn.stockouts))\
        .all()

    # 计算每个 stockin 的已抵扣数量
    stockin_deducted = {}
    for stockin in stockins:
        deducted = sum(s.quantity for s in stockin.stockouts) if stockin.stockouts else 0
        stockin_deducted[stockin.id] = deducted

    # 按 (customer, product_id) 分组计算总备货和总抵扣
    stockin_data = {}
    for stockin in stockins:
        key = (stockin.customer, stockin.product_id)
        if key not in stockin_data:
            stockin_data[key] = {
                'total_quantity': 0,
                'total_deducted': 0
            }
        stockin_data[key]['total_quantity'] += stockin.quantity
        stockin_data[key]['total_deducted'] += stockin_deducted.get(stockin.id, 0)

    # 转换为最终的备货数据字典
    final_stockin_data = {}
    for key, data in stockin_data.items():
        net_quantity = data['total_quantity'] - data['total_deducted']
        final_stockin_data[key] = net_quantity

    # 获取所有唯一的 (customer, product_id) 组合
    all_keys = set(order_data.keys()).union(set(final_stockin_data.keys()))

    # 构建库存数据列表
    inventory_data = []

    for customer, product_id in all_keys:
        product = Product.query.get(product_id)
        if not product:
            continue

        if search_product and search_product.lower() not in product.name.lower():
            continue

        order_qty = order_data.get((customer, product_id), 0)
        stockin_qty = max(0, final_stockin_data.get((customer, product_id), 0))
        total_stock = order_qty + stockin_qty

        inventory_data.append({
            'customer': customer,
            'product_id': product_id,
            'product_name': product.name,
            'product_barcode': product.barcode or '-',
            'order_quantity': order_qty,
            'stockin_quantity': stockin_qty,
            'total_stock': total_stock
        })

    # 按客户和产品名称排序
    inventory_data.sort(key=lambda x: (x['customer'], x['product_name']))

    # 计算总统计
    total_order_qty = sum(item['order_quantity'] for item in inventory_data)
    total_stockin_qty = sum(item['stockin_quantity'] for item in inventory_data)
    total_total_qty = sum(item['total_stock'] for item in inventory_data)

    return render_template('inventory.html',
                          inventory_data=inventory_data,
                          search_customer=search_customer,
                          search_product=search_product,
                          total_order_qty=total_order_qty,
                          total_stockin_qty=total_stockin_qty,
                          total_total_qty=total_total_qty)

# 获取单个产品的库存流水 API
@csrf.exempt
@app.route('/api/inventory-logs/<int:product_id>', methods=['GET'])
@api_permission_required('inventory_view')
def get_inventory_logs(product_id):
    """
    获取单个产品的库存流水记录，支持分页和筛选
    参数：
        - page: 页码（默认 1）
        - per_page: 每页数量（默认 20）
        - start_date: 开始日期（可选）
        - end_date: 结束日期（可选）
        - change_type: 变化类型（可选）
    """
    try:
        # 获取分页参数
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)

        # 限制每页最大数量
        if per_page > 100:
            per_page = 100

        # 获取筛选参数
        start_date = request.args.get('start_date', '').strip()
        end_date = request.args.get('end_date', '').strip()
        change_type = request.args.get('change_type', '').strip()

        # 构建查询
        logs_query = InventoryLog.query.filter_by(product_id=product_id)

        # 日期范围过滤
        if start_date:
            try:
                start = datetime.strptime(start_date, '%Y-%m-%d')
                logs_query = logs_query.filter(InventoryLog.change_date >= start)
            except ValueError:
                pass

        if end_date:
            try:
                end = datetime.strptime(end_date, '%Y-%m-%d')
                end = end.replace(hour=23, minute=59, second=59)
                logs_query = logs_query.filter(InventoryLog.change_date <= end)
            except ValueError:
                pass

        # 类型过滤
        if change_type:
            logs_query = logs_query.filter(InventoryLog.change_type.ilike(f'%{change_type}%'))

        # 执行分页查询
        pagination = logs_query.order_by(InventoryLog.change_date.desc()).paginate(
            page=page,
            per_page=per_page,
            error_out=False
        )

        # 格式化数据
        logs_data = []
        for log in pagination.items:
            logs_data.append({
                'id': log.id,
                'change_date': log.change_date.strftime('%Y-%m-%d %H:%M:%S'),
                'change_type': log.change_type,
                'change_quantity': log.change_quantity,
                'related_id': log.related_id or '-',
                'customer': log.customer or '-',
                'note': log.note or '-'
            })

        return jsonify({
            'success': True,
            'data': logs_data,
            'pagination': {
                'page': pagination.page,
                'per_page': pagination.per_page,
                'total': pagination.total,
                'pages': pagination.pages,
                'has_next': pagination.has_next,
                'has_prev': pagination.has_prev
            }
        })

    except Exception as e:
        print(f"获取库存流水失败：{e}")
        return jsonify({
            'success': False,
            'message': '获取流水记录失败',
            'error': str(e)
        }), 500

# 报表统计
@app.route('/reports')
@permission_required('report_manage')
def reports():
    """
    出货统计页面 - 支持客户、产品、时间段筛选
    """
    # 获取筛选条件
    search_customer = request.args.get('customer', '')
    search_product = request.args.get('product', '')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')

    # 构建查询条件
    query = StockOut.query.filter(StockOut.quantity > 0)

    # 根据客户筛选
    if search_customer:
        query = query.filter(StockOut.customer.like(f'%{search_customer}%'))

    # 根据产品筛选
    if search_product:
        query = query.join(Product).filter(Product.name.like(f'%{search_product}%'))
    else:
        # 没有产品筛选时也需要 join Product 以获取产品信息
        query = query.join(Product)

    # 根据时间段筛选
    if start_date:
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d')
            query = query.filter(StockOut.stockout_date >= start)
        except ValueError:
            pass

    if end_date:
        try:
            end = datetime.strptime(end_date, '%Y-%m-%d')
            # 包含结束日期的整天
            end = end + timedelta(days=1)
            query = query.filter(StockOut.stockout_date < end)
        except ValueError:
            pass

    # 执行查询
    stockouts = query.order_by(StockOut.stockout_date.desc()).all()

    # 统计数据
    total_quantity = sum(so.quantity for so in stockouts)
    total_amount = len(stockouts)

    return render_template('reports.html',
                          stockouts=stockouts,
                          total_quantity=total_quantity,
                          total_amount=total_amount,
                          search_customer=search_customer,
                          search_product=search_product,
                          start_date=start_date,
                          end_date=end_date,
                          active_tab=request.args.get('tab', ''))

# 备货抵扣流水查询 API
@csrf.exempt
@app.route('/api/deduction-logs')
def api_deduction_logs():
    """
    查询备货抵扣流水
    返回：抵扣时间、客户、SKU、抵扣数量、关联订单、订单备注
    """
    # 获取查询参数
    customer = request.args.get('customer', '')
    product = request.args.get('product', '')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')

    # 查询有订单关联的出货记录（即抵扣记录）
    # StockOut 中 stockin_id 不为空表示是备货抵扣产生的出货
    query = StockOut.query.filter(StockOut.stockin_id.isnot(None))

    # 根据客户筛选
    if customer:
        query = query.filter(StockOut.customer.like(f'%{customer}%'))

    # 根据产品筛选（支持产品名称或SKU/69码）
    if product:
        query = query.join(Product).filter(
            db.or_(
                Product.name.like(f'%{product}%'),
                Product.barcode.like(f'%{product}%')
            )
        )
    else:
        # 没有产品筛选时也需要 join Product 以获取产品信息
        query = query.join(Product)

    # 根据时间段筛选
    if start_date:
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d')
            query = query.filter(StockOut.stockout_date >= start)
        except ValueError:
            pass

    if end_date:
        try:
            end = datetime.strptime(end_date, '%Y-%m-%d')
            end = end + timedelta(days=1)
            query = query.filter(StockOut.stockout_date < end)
        except ValueError:
            pass

    # 执行查询，按时间倒序
    stockouts = query.order_by(StockOut.stockout_date.desc()).all()

    # 构建返回数据
    logs = []
    order_ids = set()
    for so in stockouts:
        # 获取订单备注
        order_no = None
        order_note = None
        order_id = None
        if so.order:
            order_no = so.order.order_no
            order_note = so.order.note
            order_id = so.order.id
            order_ids.add(so.order.id)

        logs.append({
            'deduction_time': so.stockout_date.strftime('%Y-%m-%d %H:%M'),
            'customer': so.customer,
            'product_name': so.product.name,
            'sku': so.product.barcode,
            'quantity': so.quantity,
            'order_no': order_no,
            'order_id': order_id,
            'order_note': order_note
        })

    # 统计数据
    stats = {
        'total_count': len(logs),
        'total_quantity': sum(so.quantity for so in stockouts),
        'total_orders': len(order_ids)
    }

    return jsonify({
        'success': True,
        'logs': logs,
        'stats': stats
    })

# 用户管理路由
@app.route('/users', methods=['GET', 'POST'])
@permission_required('user_manage')
def users():
    # 超级用户才能访问
    user = User.query.get(session['user_id'])
    if not user.is_super:
        flash('无权限访问', 'error')
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        is_super = request.form.get('is_super') == 'on'
        # 检查用户名是否存在
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash('用户名已存在', 'error')
            return redirect(url_for('users'))
        # 创建用户
        new_user = User(username=username, password=generate_password_hash(password), is_super=is_super)
        db.session.add(new_user)
        db.session.commit()
        flash('用户添加成功', 'success')
        return redirect(url_for('users'))
    users = User.query.all()
    return render_template('user.html', users=users)

# 编辑用户路由
@app.route('/user/edit/<int:id>', methods=['GET', 'POST'])
@permission_required('user_manage')
def edit_user(id):
    # 超级用户才能访问
    current_user = User.query.get(session['user_id'])
    if not current_user.is_super:
        flash('无权限访问', 'error')
        return redirect(url_for('index'))
    user = User.query.get_or_404(id)
    if request.method == 'POST':
        password = request.form['password']
        if password:
            user.password = generate_password_hash(password)
        user.is_super = request.form.get('is_super') == 'on'
        db.session.commit()
        flash('用户编辑成功', 'success')
        return redirect(url_for('users'))
    return render_template('edit_user.html', user=user)

# 切换用户状态路由
@app.route('/user/toggle/<int:id>')
@permission_required('user_manage')
def toggle_user_status(id):
    # 超级用户才能访问
    current_user = User.query.get(session['user_id'])
    if not current_user.is_super:
        flash('无权限访问', 'error')
        return redirect(url_for('index'))
    user = User.query.get_or_404(id)
    if user.is_super:
        flash('超级用户不能禁用', 'error')
        return redirect(url_for('users'))
    user.status = not user.status
    db.session.commit()
    flash('用户状态已更新', 'success')
    return redirect(url_for('users'))

# 删除用户路由
@app.route('/user/delete/<int:id>')
@permission_required('user_manage')
def delete_user(id):
    # 超级用户才能访问
    current_user = User.query.get(session['user_id'])
    if not current_user.is_super:
        flash('无权限访问', 'error')
        return redirect(url_for('index'))
    user = User.query.get_or_404(id)
    if user.is_super:
        flash('超级用户不能删除', 'error')
        return redirect(url_for('users'))
    db.session.delete(user)
    db.session.commit()
    flash('用户已删除', 'success')
    return redirect(url_for('users'))

# 权限设置路由
@app.route('/user/permission/<int:user_id>', methods=['GET', 'POST'])
@permission_required('permission_manage')
def user_permission(user_id):
    # 超级用户才能访问
    current_user = User.query.get(session['user_id'])
    if not current_user.is_super:
        flash('无权限访问', 'error')
        return redirect(url_for('index'))
    user = User.query.get_or_404(user_id)
    if request.method == 'POST':
        # 清空现有权限
        user.permissions.clear()
        # 添加新权限
        permission_ids = request.form.getlist('permission_ids')
        for pid in permission_ids:
            permission = Permission.query.get(pid)
            if permission:
                user.permissions.append(permission)
        db.session.commit()
        flash('权限设置成功', 'success')
        return redirect(url_for('users'))
    # 获取所有权限
    permissions = Permission.query.all()
    # 获取用户已有的权限
    user_permission_ids = [p.id for p in user.permissions]
    return render_template('permission.html', user=user, permissions=permissions, user_permission_ids=user_permission_ids)

# 下载统一导入模板
@app.route('/download-template')
@api_permission_required('product_manage')
def download_template():
    """下载统一导入模板 - 支持产品、订单、备货三种类型"""
    try:
        # 导入 openpyxl
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter

        # 创建 Excel 工作簿
        wb = Workbook()
        ws = wb.active
        ws.title = '统一导入模板'

        # 设置表头
        headers = ['导入类型', '客户名称', '产品名称', '69码', '数量', '时间', '是否抵扣备货', '备注']

        # 表头样式
        header_font = Font(bold=True, size=11, color='FFFFFF')
        header_alignment = Alignment(horizontal='center', vertical='center')
        header_fill = PatternFill(start_color='4472C4', end_color='4472C4', fill_type='solid')
        thin_border = Border(
            left=Side(style='thin'),
            right=Side(style='thin'),
            top=Side(style='thin'),
            bottom=Side(style='thin')
        )

        for col_idx, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.value = header
            cell.font = header_font
            cell.alignment = header_alignment
            cell.fill = header_fill
            cell.border = thin_border

        # 添加示例数据
        examples = [
            ['产品', '', '产品名称1', '6900000000001', 100, '', '', '产品导入示例'],
            ['产品', '', '产品名称2', '6900000000002', 200, '', '', ''],
            ['订单', '客户张三', '产品名称1', '', 50, '', '否', '订单导入示例'],
            ['订单', '客户李四', '产品名称2', '', 30, '', '是', '抵扣备货订单'],
            ['备货', '客户张三', '产品名称1', '', 100, '2026-03-21', '', '备货导入示例'],
            ['备货', '客户李四', '产品名称2', '', 80, '', '', '时间自动生成'],
        ]

        for row_idx, example in enumerate(examples, 2):
            for col_idx, value in enumerate(example, 1):
                cell = ws.cell(row=row_idx, column=col_idx)
                cell.value = value
                cell.alignment = Alignment(horizontal='left', vertical='center')
                cell.border = thin_border

        # 调整列宽
        col_widths = [12, 15, 20, 18, 10, 15, 15, 25]
        for i, width in enumerate(col_widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = width

        # 设置行高
        for row in range(1, len(examples) + 2):
            ws.row_dimensions[row].height = 22

        # 添加填写说明工作表
        ws2 = wb.create_sheet('填写说明')

        instructions = [
            ['统一导入模板填写说明', ''],
            ['', ''],
            ['字段说明：', ''],
            ['导入类型', '必填。可选值：产品、订单、备货'],
            ['客户名称', '订单和备货必填，产品导入时可为空'],
            ['产品名称', '必填。必须与系统中已存在的产品名称完全匹配（订单/备货）'],
            ['69 码', '产品导入时填写，订单/备货导入时可为空'],
            ['数量', '必填。产品：初始库存；订单：订单数量；备货：备货数量'],
            ['时间', '备货导入时填写备货时间（格式：YYYY-MM-DD），其他可为空'],
            ['是否抵扣备货', '订单专用。填写是或否，其他类型可为空'],
            ['备注', '可选。填写备注信息'],
            ['', ''],
            ['注意事项：', ''],
            ['1. 导入类型必须准确', '系统根据导入类型判断处理逻辑'],
            ['2. 产品名称必须存在', '订单/备货导入时，产品必须已在系统中存在'],
            ['3. 客户名称必须存在', '订单/备货导入时，客户必须已在系统中存在'],
            ['4. 数量必须为正整数', '不支持负数或小数'],
            ['5. 时间格式', '备货时间格式：YYYY-MM-DD，如 2026-03-21'],
            ['6. 时间自动生成', '订单时间自动按当天北京时间生成'],
        ]

        for row_idx, row_data in enumerate(instructions, 1):
            for col_idx, value in enumerate(row_data, 1):
                cell = ws2.cell(row=row_idx, column=col_idx)
                cell.value = value
                if row_idx == 1:
                    cell.font = Font(bold=True, size=14)
                elif '：' in str(value) and col_idx == 1:
                    cell.font = Font(bold=True)

        ws2.column_dimensions['A'].width = 25
        ws2.column_dimensions['B'].width = 50

        # 保存到内存
        import io
        from urllib.parse import quote

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)

        # 验证生成的文件是否有效
        file_size = len(output.getvalue())
        if file_size == 0:
            raise Exception("生成的 Excel 文件为空")

        # 生成带时间戳的文件名
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'统一导入模板_{timestamp}.xlsx'

        # 创建响应
        response = make_response(output.getvalue())

        # 设置Content-Disposition，使用RFC 5987编码处理中文文件名
        # 这样浏览器会弹出"另存为"对话框
        encoded_filename = quote(filename)
        response.headers['Content-Disposition'] = f"attachment; filename*=UTF-8''{encoded_filename}"
        response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        response.headers['Content-Length'] = str(file_size)
        # 添加Cache-Control防止缓存
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'

        print(f"统一导入模板下载成功，文件大小：{file_size} 字节")
        return response

    except Exception as e:
        import traceback
        error_traceback = traceback.format_exc()
        print(f"模板下载错误：{error_traceback}")

        # 返回详细的错误信息给前端
        from flask import jsonify
        return jsonify({
            'success': False,
            'error': f'模板生成失败：{str(e)}',
            'details': '请检查服务器日志或联系管理员'
        }), 500

# 获取当前用户桌面路径
@app.route('/get-desktop-path', methods=['GET'])
@api_permission_required('product_manage')
def get_desktop_path():
    import platform

    try:
        system = platform.system()

        if system == 'Windows' or system == 'Darwin':
            desktop = os.path.join(os.path.expanduser('~'), 'Desktop')
        elif system == 'Linux':
            xdg_desktop = os.environ.get('XDG_DESKTOP_DIR')
            if xdg_desktop and os.path.exists(xdg_desktop):
                desktop = xdg_desktop
            else:
                desktop = os.path.join(os.path.expanduser('~'), 'Desktop')
                if not os.path.exists(desktop):
                    desktop = os.path.join(os.path.expanduser('~'), 'desktop')
        else:
            desktop = os.path.join(os.path.expanduser('~'), 'Desktop')

        if not os.path.exists(desktop):
            return jsonify({
                'success': False,
                'error': f'无法找到桌面路径: {desktop}'
            }), 404

        return jsonify({
            'success': True,
            'desktopPath': desktop,
            'system': system,
            'username': os.path.basename(os.path.expanduser('~'))
        })

    except Exception as e:
        import traceback
        error_traceback = traceback.format_exc()
        print(f"获取桌面路径错误：{error_traceback}")

        return jsonify({
            'success': False,
            'error': f'获取桌面路径失败：{str(e)}'
        }), 500

# 复制模板文件到用户桌面
@app.route('/copy-template-to-desktop', methods=['POST'])
@api_permission_required('product_manage')
def copy_template_to_desktop():
    import shutil

    try:
        data = request.get_json()
        desktop_path = data.get('desktopPath')

        if not desktop_path:
            return jsonify({
                'success': False,
                'error': '未提供桌面路径'
            }), 400

        template_path = os.path.join(app.root_path, 'static', 'files', '模板.xlsx')

        if not os.path.exists(template_path):
            return jsonify({
                'success': False,
                'error': f'模板文件不存在: {template_path}'
            }), 404

        if not os.path.exists(desktop_path):
            return jsonify({
                'success': False,
                'error': f'桌面路径不存在: {desktop_path}'
            }), 404

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'产品导入模板_{timestamp}.xlsx'
        destination = os.path.join(desktop_path, filename)

        shutil.copy2(template_path, destination)

        return jsonify({
            'success': True,
            'message': '模板文件已成功复制到桌面',
            'savedPath': destination,
            'filename': filename
        })

    except PermissionError:
        return jsonify({
            'success': False,
            'error': '文件复制失败：权限不足。请以管理员身份运行或选择其他目录'
        }), 403

    except Exception as e:
        import traceback
        error_traceback = traceback.format_exc()
        print(f"复制模板文件错误：{error_traceback}")

        return jsonify({
            'success': False,
            'error': f'复制模板文件失败：{str(e)}'
        }), 500

# 使用文件保存对话框导出模板
@csrf.exempt
@app.route('/save-template-dialog', methods=['POST'])
@api_permission_required('product_manage')
def save_template_dialog():
    try:
        # 使用 tkinter 打开 Windows 文件保存对话框
        from tkinter import Tk, filedialog

        # 获取模板类型参数
        data = request.get_json() or {}
        template_type = data.get('type', 'product')

        # 创建隐藏的主窗口
        root = Tk()
        root.withdraw()  # 隐藏主窗口
        root.attributes('-topmost', True)  # 设置为顶层窗口

        # 根据模板类型生成默认文件名和模板路径
        if template_type == 'stockin':
            default_filename = f"备货导入模板_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            template_path = os.path.join(app.root_path, 'static', 'files', '入库单批量上传模板.xlsx')
            dialog_title = "保存备货模板"
        elif template_type == 'order':
            default_filename = f"订单导入模板_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            template_path = os.path.join(app.root_path, 'static', 'files', '订单批量上传模板.xlsx')
            dialog_title = "保存订单模板"
        elif template_type == 'stockout':
            default_filename = f"出库导入模板_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            template_path = os.path.join(app.root_path, 'static', 'files', '出库单批量上传模板.xlsx')
            dialog_title = "保存出库模板"
        else:  # product
            default_filename = f"产品导入模板_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            template_path = os.path.join(app.root_path, 'static', 'files', '模板.xlsx')
            dialog_title = "保存生产模板"

        # 打开文件保存对话框
        file_path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[
                ("Excel 文件", "*.xlsx"),
                ("所有文件", "*.*")
            ],
            title=dialog_title,
            initialfile=default_filename
        )

        # 销毁窗口
        root.destroy()

        # 用户取消保存
        if not file_path:
            return jsonify({
                'success': False,
                'error': '用户取消保存'
            }), 400

        # 确保文件扩展名正确
        if not file_path.lower().endswith('.xlsx'):
            file_path += '.xlsx'

        # 检查模板文件是否存在
        if not os.path.exists(template_path):
            return jsonify({
                'success': False,
                'error': f'模板文件不存在：{template_path}'
            }), 404

        # 检查目标目录是否存在
        target_dir = os.path.dirname(file_path)
        if not os.path.exists(target_dir):
            return jsonify({
                'success': False,
                'error': f'目标目录不存在：{target_dir}'
            }), 400

        # 复制文件
        shutil.copy2(template_path, file_path)

        return jsonify({
            'success': True,
            'message': '模板保存成功',
            'savedPath': file_path
        })

    except PermissionError as e:
        error_msg = str(e)
        print(f"权限错误：{error_msg}")
        return jsonify({
            'success': False,
            'error': '保存失败：权限不足。请选择其他有写入权限的目录，或以管理员身份运行。'
        }), 403

    except OSError as e:
        error_msg = str(e)
        print(f"系统错误：{error_msg}")

        # 判断是否是文件被占用
        if 'being used by another process' in error_msg or '无法访问文件' in error_msg:
            return jsonify({
                'success': False,
                'error': '保存失败：目标文件正在被其他程序使用。请关闭相关程序后重试。'
            }), 409

        # 判断是否是磁盘空间不足
        if 'not enough space' in error_msg or '没有足够的空间' in error_msg:
            return jsonify({
                'success': False,
                'error': '保存失败：磁盘空间不足。请选择其他磁盘分区。'
            }), 400

        return jsonify({
            'success': False,
            'error': f'保存失败：系统错误 - {str(e)}'
        }), 500

    except Exception as e:
        import traceback
        error_traceback = traceback.format_exc()
        print(f"保存模板对话框错误：{error_traceback}")

        return jsonify({
            'success': False,
            'error': f'保存失败：{str(e)}'
        }), 500

# 批量导入产品
@app.route('/batch-import', methods=['POST'])
@api_permission_required('product_manage')
def batch_import():
    """
    批量导入产品 - 重构版
    使用统一的批量导入模板,代码从284行减少到约50行
    """
    from utils.batch_handler import batch_import_template
    from utils.excel_handler import validate_required_field

    def process_product_row(row, get_cell_value):
        """处理单行产品数据"""
        # 读取单元格数据
        name = get_cell_value(row, 1)
        barcode = get_cell_value(row, 2)
        initial_stock = get_cell_value(row, 3)

        # 验证必填字段
        valid, error = validate_required_field(name, '产品名称', row)
        if not valid:
            return False, error

        # 清理数据
        name = str(name).strip()
        barcode = str(barcode).strip() if barcode else ''

        # 验证库存数据
        if initial_stock is None:
            initial_stock = 0
        try:
            if isinstance(initial_stock, str):
                initial_stock = initial_stock.strip()
                initial_stock = 0 if initial_stock == '' else int(float(initial_stock))
            elif isinstance(initial_stock, float):
                initial_stock = int(initial_stock)
            else:
                initial_stock = int(initial_stock)

            if initial_stock < 0:
                initial_stock = 0
        except (ValueError, TypeError):
            return False, f'第{row}行：初始库存必须是数字，实际值：{initial_stock}'

        # 检查是否已存在
        existing = Product.query.filter_by(name=name).first()
        if existing:
            return False, None  # 跳过已存在的产品

        # 创建产品
        product = Product(
            name=name,
            barcode=barcode,
            initial_stock=initial_stock,
            current_stock=initial_stock
        )
        db.session.add(product)
        db.session.flush()

        # 添加库存日志
        log = InventoryLog(
            product_id=product.id,
            change_type='初始库存',
            change_quantity=initial_stock,
            related_id=str(product.id),
            note='批量导入'
        )
        db.session.add(log)

        return True, None

    # 检查文件
    if 'file' not in request.files:
        return api_error('没有文件')

    file = request.files['file']

    # 使用批量导入模板
    return batch_import_template(
        file,
        ['产品名称', '69 码', '初始库存'],
        process_product_row,
        '产品',
        db
    )

# ==================== 皮套管理模块 ====================
# 注意: 皮套编号生成函数已移至 utils/number_generator.py

@csrf.exempt
@app.route('/api/case-search')
@api_permission_required('case_manage')
def case_search():
    """皮套搜索 API"""
    query = request.args.get('q', '')
    if query:
        cases = Case.query.filter(Case.name.contains(query)).all()
    else:
        cases = Case.query.limit(20).all()
    result = []
    for c in cases:
        result.append({
            'id': c.id,
            'name': c.name,
            'barcode': c.barcode or '',
            'current_stock': c.current_stock
        })
    return jsonify(result)

@app.route('/api/batch-submit-case-stockins', methods=['POST'])
@csrf.exempt
@api_permission_required('case_manage')
def batch_submit_case_stockins():
    """批量提交皮套入库 API"""
    try:
        data = request.get_json()
        stockins_data = data.get('stockins', [])

        if not stockins_data:
            return jsonify({
                'success': False,
                'message': '没有入库数据'
            })

        success_count = 0
        failed_stockins = []

        for stockin_data in stockins_data:
            try:
                stockin_no = generate_case_stockin_number(db, CaseStockIn)

                product_id_str = str(stockin_data.get('productId', '')).strip()
                quantity_str = str(stockin_data.get('quantity', '')).strip()
                stockin_date_str = stockin_data.get('stockinDate', '')

                if not product_id_str:
                    failed_stockins.append({'stockin': stockin_data, 'error': '请选择皮套'})
                    continue

                if not quantity_str or quantity_str == '0':
                    failed_stockins.append({'stockin': stockin_data, 'error': '请输入有效的数量'})
                    continue

                if not stockin_date_str:
                    failed_stockins.append({'stockin': stockin_data, 'error': '请选择入库时间'})
                    continue

                try:
                    product_id = int(product_id_str)
                    quantity = int(quantity_str)
                    stockin_date = datetime.strptime(stockin_date_str, '%Y-%m-%d')
                except ValueError:
                    failed_stockins.append({'stockin': stockin_data, 'error': '数据格式错误'})
                    continue

                case_obj = Case.query.get(product_id)
                if not case_obj:
                    failed_stockins.append({'stockin': stockin_data, 'error': '皮套不存在'})
                    continue

                if quantity <= 0:
                    failed_stockins.append({'stockin': stockin_data, 'error': '数量必须大于 0'})
                    continue

                note = stockin_data.get('note', '')
                customer = stockin_data.get('customer', '')

                stockin = CaseStockIn(
                    stockin_no=stockin_no,
                    stockin_date=stockin_date,
                    customer=customer,
                    case_id=product_id,
                    quantity=quantity,
                    note=note
                )
                db.session.add(stockin)

                case_obj.current_stock += quantity

                log = CaseInventoryLog(
                    case_id=product_id,
                    change_type='入库',
                    change_quantity=quantity,
                    related_id=stockin_no,
                    note=f'入库：{stockin_no}',
                    customer=customer
                )
                db.session.add(log)

                success_count += 1

            except Exception as e:
                print(f"处理皮套入库时出错：{e}")
                failed_stockins.append({'stockin': stockin_data, 'error': str(e)})

        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'成功提交 {success_count} 个入库',
            'success_count': success_count,
            'failed_count': len(failed_stockins),
            'failed_stockins': failed_stockins
        })

    except Exception as e:
        print(f"批量提交皮套入库出错：{e}")
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': '批量提交失败',
            'error': str(e)
        })

@app.route('/api/batch-submit-case-stockouts', methods=['POST'])
@csrf.exempt
@api_permission_required('case_manage')
def batch_submit_case_stockouts():
    """批量提交皮套出库 API"""
    try:
        data = request.get_json()
        stockouts_data = data.get('stockouts', [])

        if not stockouts_data:
            return jsonify({
                'success': False,
                'message': '没有出库数据'
            })

        success_count = 0
        failed_stockouts = []

        for stockout_data in stockouts_data:
            try:
                stockout_no = generate_case_stockout_number(db, CaseStockOut)

                customer = stockout_data.get('customer', '')
                product_id_str = str(stockout_data.get('productId', '')).strip()
                quantity_str = str(stockout_data.get('quantity', '')).strip()
                stockout_date_str = stockout_data.get('stockoutDate', '')

                if not customer:
                    failed_stockouts.append({'stockout': stockout_data, 'error': '请选择客户'})
                    continue

                if not product_id_str:
                    failed_stockouts.append({'stockout': stockout_data, 'error': '请选择皮套'})
                    continue

                if not quantity_str or quantity_str == '0':
                    failed_stockouts.append({'stockout': stockout_data, 'error': '请输入有效的数量'})
                    continue

                if not stockout_date_str:
                    failed_stockouts.append({'stockout': stockout_data, 'error': '请选择出库时间'})
                    continue

                try:
                    product_id = int(product_id_str)
                    quantity = int(quantity_str)
                    stockout_date = datetime.strptime(stockout_date_str, '%Y-%m-%d')
                except ValueError:
                    failed_stockouts.append({'stockout': stockout_data, 'error': '数据格式错误'})
                    continue

                case_obj = Case.query.get(product_id)
                if not case_obj:
                    failed_stockouts.append({'stockout': stockout_data, 'error': '皮套不存在'})
                    continue

                if case_obj.current_stock < quantity:
                    failed_stockouts.append({'stockout': stockout_data, 'error': '库存不足'})
                    continue

                note = stockout_data.get('note', '')

                stockout = CaseStockOut(
                    stockout_no=stockout_no,
                    stockout_date=stockout_date,
                    case_id=product_id,
                    quantity=quantity,
                    customer=customer,
                    note=note
                )
                db.session.add(stockout)

                case_obj.current_stock -= quantity

                log = CaseInventoryLog(
                    case_id=product_id,
                    change_type='出库',
                    change_quantity=-quantity,
                    related_id=stockout_no,
                    note=f'出库：{stockout_no}',
                    customer=customer
                )
                db.session.add(log)

                success_count += 1

            except Exception as e:
                print(f"处理皮套出库时出错：{e}")
                failed_stockouts.append({'stockout': stockout_data, 'error': str(e)})

        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'成功提交 {success_count} 个出库',
            'success_count': success_count,
            'failed_count': len(failed_stockouts),
            'failed_stockouts': failed_stockouts
        })

    except Exception as e:
        print(f"批量提交皮套出库出错：{e}")
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': '批量提交失败',
            'error': str(e)
        })

@csrf.exempt
@app.route('/api/case-stockin-info/<int:stockin_id>')
@api_permission_required('case_manage')
def case_stockin_info(stockin_id):
    """获取皮套入库详情 API"""
    stockin = CaseStockIn.query.get_or_404(stockin_id)
    return jsonify({
        'id': stockin.id,
        'stockin_no': stockin.stockin_no,
        'case_id': stockin.case_id,
        'case_name': stockin.case.name,
        'quantity': stockin.quantity
    })

@csrf.exempt
@app.route('/api/case-inventory-logs/<int:case_id>')
@api_permission_required('case_manage')
def case_inventory_logs(case_id):
    """获取皮套库存流水 API"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    change_type = request.args.get('change_type', '')

    query = CaseInventoryLog.query.filter_by(case_id=case_id)

    if start_date:
        start = datetime.strptime(start_date, '%Y-%m-%d')
        query = query.filter(CaseInventoryLog.change_date >= start)

    if end_date:
        end = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
        query = query.filter(CaseInventoryLog.change_date < end)

    if change_type:
        query = query.filter(CaseInventoryLog.change_type == change_type)

    query = query.order_by(CaseInventoryLog.change_date.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    logs = pagination.items

    result = []
    for log in logs:
        result.append({
            'id': log.id,
            'change_type': log.change_type,
            'change_quantity': log.change_quantity,
            'change_date': log.change_date.strftime('%Y-%m-%d %H:%M:%S'),
            'related_id': log.related_id or '',
            'note': log.note or '',
            'customer': log.customer or ''
        })

    return jsonify({
        'logs': result,
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page
    })

@csrf.exempt
@app.route('/api/available-case-stockins')
@api_permission_required('case_manage')
def available_case_stockins():
    """获取可用皮套入库列表 API"""
    case_id = request.args.get('case_id', type=int)

    query = CaseStockIn.query.filter(CaseStockIn.quantity > 0)

    if case_id:
        query = query.filter(CaseStockIn.case_id == case_id)

    stockins = query.all()
    result = []

    for stockin in stockins:
        result.append({
            'id': stockin.id,
            'stockin_no': stockin.stockin_no,
            'case_id': stockin.case_id,
            'case_name': stockin.case.name,
            'quantity': stockin.quantity
        })

    result.sort(key=lambda x: x['quantity'], reverse=True)

    return jsonify(result)

@app.route('/case-stockins')
@api_permission_required('case_manage')
def case_stockins_page():
    """皮套入库管理页面"""
    customers = ['MINISO 国际', 'MINISO 国内', 'MINISO 电商']
    return render_template('case.html', customers=customers, is_home=False)

@app.route('/case-stockouts')
@api_permission_required('case_manage')
def case_stockouts_page():
    """皮套出库管理页面"""
    customers = ['MINISO 国际', 'MINISO 国内', 'MINISO 电商']
    return render_template('case_out.html', customers=customers, is_home=False)

@app.route('/case-inventory')
@api_permission_required('case_manage')
def case_inventory_page():
    """皮套库存查询页面"""
    return render_template('case_inventory.html', is_home=False)

@csrf.exempt
@app.route('/api/case-stockins')
@api_permission_required('case_manage')
def api_case_stockins():
    """获取皮套入库列表 API（支持搜索）"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    customer = request.args.get('customer', '')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    quantity_min = request.args.get('quantity_min', type=int)
    quantity_max = request.args.get('quantity_max', type=int)

    query = CaseStockIn.query

    if customer:
        query = query.filter(CaseStockIn.customer.contains(customer))

    if start_date:
        start = datetime.strptime(start_date, '%Y-%m-%d')
        query = query.filter(CaseStockIn.stockin_date >= start)

    if end_date:
        end = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
        query = query.filter(CaseStockIn.stockin_date < end)

    if quantity_min:
        query = query.filter(CaseStockIn.quantity >= quantity_min)

    if quantity_max:
        query = query.filter(CaseStockIn.quantity <= quantity_max)

    query = query.order_by(CaseStockIn.stockin_date.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    result = []
    for stockin in pagination.items:
        result.append({
            'id': stockin.id,
            'stockin_no': stockin.stockin_no,
            'stockin_date': stockin.stockin_date.strftime('%Y-%m-%d'),
            'customer': stockin.customer,
            'case_id': stockin.case_id,
            'case_name': stockin.case.name,
            'case_barcode': stockin.case.barcode or '',
            'quantity': stockin.quantity,
            'note': stockin.note or ''
        })

    return jsonify({
        'stockins': result,
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page
    })

@csrf.exempt
@app.route('/api/case-stockouts')
@api_permission_required('case_manage')
def api_case_stockouts():
    """获取皮套出库列表 API（支持搜索）"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    customer = request.args.get('customer', '')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    quantity_min = request.args.get('quantity_min', type=int)
    quantity_max = request.args.get('quantity_max', type=int)

    query = CaseStockOut.query

    if customer:
        query = query.filter(CaseStockOut.customer.contains(customer))

    if start_date:
        start = datetime.strptime(start_date, '%Y-%m-%d')
        query = query.filter(CaseStockOut.stockout_date >= start)

    if end_date:
        end = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
        query = query.filter(CaseStockOut.stockout_date < end)

    if quantity_min:
        query = query.filter(CaseStockOut.quantity >= quantity_min)

    if quantity_max:
        query = query.filter(CaseStockOut.quantity <= quantity_max)

    query = query.order_by(CaseStockOut.stockout_date.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    result = []
    for stockout in pagination.items:
        result.append({
            'id': stockout.id,
            'stockout_no': stockout.stockout_no,
            'stockout_date': stockout.stockout_date.strftime('%Y-%m-%d'),
            'customer': stockout.customer or '',
            'case_id': stockout.case_id,
            'case_name': stockout.case.name,
            'case_barcode': stockout.case.barcode or '',
            'quantity': stockout.quantity,
            'note': stockout.note or ''
        })

    return jsonify({
        'stockouts': result,
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page
    })

@csrf.exempt
@app.route('/api/case-stockin/<int:stockin_id>', methods=['GET'])
@api_permission_required('case_manage')
def get_case_stockin(stockin_id):
    """获取单个皮套入库记录"""
    stockin = CaseStockIn.query.get_or_404(stockin_id)
    return jsonify({
        'id': stockin.id,
        'stockin_no': stockin.stockin_no,
        'stockin_date': stockin.stockin_date.strftime('%Y-%m-%d'),
        'customer': stockin.customer,
        'case_id': stockin.case_id,
        'case_name': stockin.case.name,
        'quantity': stockin.quantity,
        'note': stockin.note or ''
    })

@app.route('/api/case-stockin/<int:stockin_id>', methods=['PUT'])
@api_permission_required('case_manage')
def update_case_stockin(stockin_id):
    """更新皮套入库记录"""
    try:
        data = request.get_json()
        stockin = CaseStockIn.query.get_or_404(stockin_id)

        old_quantity = stockin.quantity
        new_quantity = data.get('quantity', old_quantity)
        quantity_change = new_quantity - old_quantity

        stockin.customer = data.get('customer', stockin.customer)
        stockin.stockin_date = datetime.strptime(data.get('stockin_date', stockin.stockin_date.strftime('%Y-%m-%d')), '%Y-%m-%d')
        stockin.quantity = new_quantity
        stockin.note = data.get('note', stockin.note)

        case_obj = Case.query.get(stockin.case_id)
        if case_obj:
            case_obj.current_stock += quantity_change

            log = CaseInventoryLog(
                case_id=stockin.case_id,
                change_type='入库调整',
                change_quantity=quantity_change,
                related_id=stockin.stockin_no,
                note=f'入库调整：{stockin.stockin_no}'
            )
            db.session.add(log)

        db.session.commit()

        return jsonify({'success': True, 'message': '更新成功'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'更新失败：{str(e)}'})

@app.route('/api/case-stockin/<int:stockin_id>', methods=['DELETE'])
@api_permission_required('case_manage')
def delete_case_stockin(stockin_id):
    """删除皮套入库记录"""
    try:
        stockin = CaseStockIn.query.get_or_404(stockin_id)

        if stockin.stockouts:
            return jsonify({'success': False, 'message': '该入库记录已有出库，无法删除'})

        case_obj = Case.query.get(stockin.case_id)
        if case_obj:
            case_obj.current_stock -= stockin.quantity

            log = CaseInventoryLog(
                case_id=stockin.case_id,
                change_type='删除入库',
                change_quantity=-stockin.quantity,
                related_id=stockin.stockin_no,
                note=f'删除入库：{stockin.stockin_no}'
            )
            db.session.add(log)

        db.session.delete(stockin)
        db.session.commit()

        return jsonify({'success': True, 'message': '删除成功'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'删除失败：{str(e)}'})

@csrf.exempt
@app.route('/api/case-stockout/<int:stockout_id>', methods=['GET'])
@api_permission_required('case_manage')
def get_case_stockout(stockout_id):
    """获取单个皮套出库记录"""
    stockout = CaseStockOut.query.get_or_404(stockout_id)
    return jsonify({
        'id': stockout.id,
        'stockout_no': stockout.stockout_no,
        'stockout_date': stockout.stockout_date.strftime('%Y-%m-%d'),
        'customer': stockout.customer or '',
        'case_id': stockout.case_id,
        'case_name': stockout.case.name,
        'quantity': stockout.quantity,
        'note': stockout.note or ''
    })

@app.route('/api/case-stockout/<int:stockout_id>', methods=['PUT'])
@api_permission_required('case_manage')
def update_case_stockout(stockout_id):
    """更新皮套出库记录"""
    try:
        data = request.get_json()
        stockout = CaseStockOut.query.get_or_404(stockout_id)

        old_quantity = stockout.quantity
        new_quantity = data.get('quantity', old_quantity)
        quantity_change = new_quantity - old_quantity

        stockout.customer = data.get('customer', stockout.customer)
        stockout.stockout_date = datetime.strptime(data.get('stockout_date', stockout.stockout_date.strftime('%Y-%m-%d')), '%Y-%m-%d')
        stockout.quantity = new_quantity
        stockout.note = data.get('note', stockout.note)

        case_obj = Case.query.get(stockout.case_id)
        if case_obj:
            case_obj.current_stock -= quantity_change

            log = CaseInventoryLog(
                case_id=stockout.case_id,
                change_type='出库调整',
                change_quantity=-quantity_change,
                related_id=stockout.stockout_no,
                note=f'出库调整：{stockout.stockout_no}'
            )
            db.session.add(log)

        db.session.commit()

        return jsonify({'success': True, 'message': '更新成功'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'更新失败：{str(e)}'})

@app.route('/api/case-stockout/<int:stockout_id>', methods=['DELETE'])
@api_permission_required('case_manage')
def delete_case_stockout(stockout_id):
    """删除皮套出库记录"""
    try:
        stockout = CaseStockOut.query.get_or_404(stockout_id)

        case_obj = Case.query.get(stockout.case_id)
        if case_obj:
            case_obj.current_stock += stockout.quantity

            log = CaseInventoryLog(
                case_id=stockout.case_id,
                change_type='删除出库',
                change_quantity=stockout.quantity,
                related_id=stockout.stockout_no,
                note=f'删除出库：{stockout.stockout_no}'
            )
            db.session.add(log)

        db.session.delete(stockout)
        db.session.commit()

        return jsonify({'success': True, 'message': '删除成功'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'删除失败：{str(e)}'})

@csrf.exempt
@app.route('/api/case-inventory-summary')
@api_permission_required('case_manage')
def case_inventory_summary():
    """获取皮套库存汇总"""
    cases = Case.query.all()
    result = []

    for case in cases:
        total_in = sum(s.quantity for s in case.stockins) if case.stockins else 0
        total_out = sum(s.quantity for s in case.stockouts) if case.stockouts else 0

        result.append({
            'id': case.id,
            'name': case.name,
            'barcode': case.barcode or '',
            'initial_stock': case.initial_stock,
            'total_in': total_in,
            'total_out': total_out,
            'current_stock': case.current_stock
        })

    return jsonify(result)

@app.route('/cases')
def cases():
    """皮套管理首页（暂存列表页面）"""
    return redirect(url_for('case_stockins_page'))

@app.route('/case-products', methods=['GET', 'POST'])
@api_permission_required('case_manage')
def case_products():
    """皮套基础数据管理页面"""
    if request.method == 'POST':
        try:
            name = request.form.get('name', '').strip()
            barcode = request.form.get('barcode', '').strip()
            image = request.form.get('image', '')

            if not name:
                flash('皮套名称不能为空', 'error')
                return redirect(url_for('case_products'))

            # 检查名称是否重复
            existing = Case.query.filter_by(name=name).first()
            if existing:
                flash('该皮套名称已存在', 'error')
                return redirect(url_for('case_products'))

            case_obj = Case(
                name=name,
                barcode=barcode or None,
                image=image or None,
                initial_stock=0,
                current_stock=0
            )
            db.session.add(case_obj)
            db.session.commit()

            flash('皮套添加成功', 'success')
            return redirect(url_for('case_products'))

        except Exception as e:
            db.session.rollback()
            flash(f'添加失败：{str(e)}', 'error')

    cases = Case.query.order_by(Case.create_time.desc()).all()
    return render_template('case_product.html', cases=cases, is_home=False)

@csrf.exempt
@app.route('/api/case-product/<int:case_id>', methods=['DELETE'])
@api_permission_required('case_manage')
def delete_case_product(case_id):
    """删除皮套基础数据"""
    try:
        case_obj = Case.query.get_or_404(case_id)

        # 检查是否有相关业务记录
        if case_obj.stockins:
            return jsonify({'success': False, 'message': '该皮套已有入库记录，无法删除'})

        if case_obj.stockouts:
            return jsonify({'success': False, 'message': '该皮套已有出库记录，无法删除'})

        db.session.delete(case_obj)
        db.session.commit()

        return jsonify({'success': True, 'message': '删除成功'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'删除失败：{str(e)}'})


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        # 数据库字段已初始化，无需重复添加
        # 初始化权限数据
        if not Permission.query.first():
            # 添加基础权限
            permissions = [
                {'name': '首页', 'code': 'index', 'parent_id': None},
                {'name': '产品管理', 'code': 'product_manage', 'parent_id': None},
                {'name': '订单管理', 'code': 'order_manage', 'parent_id': None},
                {'name': '备货管理', 'code': 'stockin_manage', 'parent_id': None},
                {'name': '出货管理', 'code': 'stockout_manage', 'parent_id': None},
                {'name': '库存查询', 'code': 'inventory_manage', 'parent_id': None},
                {'name': '报表统计', 'code': 'report_manage', 'parent_id': None},
                {'name': '用户管理', 'code': 'user_manage', 'parent_id': None},
                {'name': '权限设置', 'code': 'permission_manage', 'parent_id': None},
                {'name': '皮套管理', 'code': 'case_manage', 'parent_id': None},
            ]
            for p in permissions:
                permission = Permission(name=p['name'], code=p['code'], parent_id=p['parent_id'])
                db.session.add(permission)
            db.session.commit()
        # 初始化超级用户
        if not User.query.filter_by(is_super=True).first():
            # 创建超级用户，默认密码123456
            super_user = User(username='admin', password=generate_password_hash('123456'), is_super=True)
            db.session.add(super_user)
            db.session.commit()
    # 允许局域网访问，host=0.0.0.0表示监听所有网络接口
    app.run(host='0.0.0.0', port=5003, debug=True)
