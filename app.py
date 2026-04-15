from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, make_response
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import os
from sqlalchemy import text
from jinja2 import Environment
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

app = Flask(__name__)
app.secret_key = 'erp_secret_key_2025'
# 配置上传路径
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')
# 创建上传目录
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}
# 配置上传路径
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')
# 创建上传目录
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}
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
# 配置SQLite数据库（本地存储，无需额外数据库服务）
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///erp.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)



# 数据库模型定义
class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False, comment='产品编号')
    name = db.Column(db.String(100), nullable=False, comment='产品名称')
    spec = db.Column(db.String(100), comment='产品规格')
    barcode = db.Column(db.String(50), comment='69码/商品条码')
    origin = db.Column(db.String(50), comment='产地（东莞/湖北）')
    image = db.Column(db.String(200), comment='产品图片路径')
    initial_stock = db.Column(db.Integer, default=0, comment='初始库存')
    current_stock = db.Column(db.Integer, default=0, comment='当前库存')
    create_time = db.Column(db.DateTime, default=datetime.now, comment='创建时间')

    def __repr__(self):
        return f'<Product {self.name}>'

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_no = db.Column(db.String(20), unique=True, nullable=False, comment='订单编号')
    customer = db.Column(db.String(100), nullable=False, comment='客户名称')
    order_date = db.Column(db.DateTime, default=datetime.now, comment='下单时间')
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False, comment='产品ID')
    quantity = db.Column(db.Integer, nullable=False, comment='订单数量')
    status = db.Column(db.String(20), default='待备货', comment='订单状态：待备货、部分备货、已备货、待出货、已出货、已取消')
    note = db.Column(db.Text, comment='备注')
    product = db.relationship('Product', backref=db.backref('orders', lazy=True))

    def __repr__(self):
        return f'<Order {self.order_no}>'

class StockIn(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    stockin_no = db.Column(db.String(20), unique=True, nullable=False, comment='备货编号')
    stockin_date = db.Column(db.DateTime, default=datetime.now, comment='备货时间')
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False, comment='产品ID')
    quantity = db.Column(db.Integer, nullable=False, comment='备货数量')
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), comment='关联订单ID')
    note = db.Column(db.Text, comment='备注')
    product = db.relationship('Product', backref=db.backref('stockins', lazy=True))
    order = db.relationship('Order', backref=db.backref('stockins', lazy=True))

    def __repr__(self):
        return f'<StockIn {self.stockin_no}>'

class StockOut(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    stockout_no = db.Column(db.String(20), unique=True, nullable=False, comment='出货编号')
    stockout_date = db.Column(db.DateTime, default=datetime.now, comment='出货时间')
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False, comment='产品ID')
    quantity = db.Column(db.Integer, nullable=False, comment='出货数量')
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False, comment='关联订单ID')
    stockin_id = db.Column(db.Integer, db.ForeignKey('stock_in.id'), comment='关联备货ID')
    note = db.Column(db.Text, comment='备注')
    product = db.relationship('Product', backref=db.backref('stockouts', lazy=True))
    order = db.relationship('Order', backref=db.backref('stockouts', lazy=True))
    stockin = db.relationship('StockIn', backref=db.backref('stockouts', lazy=True))

class InventoryLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False, comment='产品ID')
    change_type = db.Column(db.String(20), nullable=False, comment='变化类型：初始库存、备货、出货、订单调整')
    change_quantity = db.Column(db.Integer, nullable=False, comment='变化数量（正数为增加，负数为减少）')
    change_date = db.Column(db.DateTime, default=datetime.now, comment='变化时间')
    related_id = db.Column(db.String(20), comment='关联单据编号')
    note = db.Column(db.Text, comment='备注')
    product = db.relationship('Product', backref=db.backref('inventory_logs', lazy=True))

# 用户管理模型
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False, comment='用户名')
    password = db.Column(db.String(100), nullable=False, comment='密码')
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
        for p in self.permissions:
            if p.code == permission_code:
                return True
        return False

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
    flash('已退出登录', 'success')
    # 清除cookie
    resp = make_response(redirect(url_for('login')))
    resp.set_cookie('user_id', '', max_age=0)
    return resp

@app.route('/')
def index():
    if not session.get('user_id'):
        return redirect(url_for('login'))
    return render_template('index.html')

# 产品管理
@app.route('/products', methods=['GET', 'POST'])
@permission_required('product_manage')
def products():
    if request.method == 'POST':
        code = request.form['code']
        name = request.form['name']
        spec = request.form['spec']
        barcode = request.form['barcode']
        origin = request.form['origin']
        image = request.form.get('image', '')
        initial_stock = int(request.form['initial_stock'])
        # 检查产品编号是否已存在
        existing_product = Product.query.filter_by(code=code).first()
        if existing_product:
            flash('产品编号已存在！', 'error')
            return redirect(url_for('products'))
        # 创建产品
        product = Product(code=code, name=name, spec=spec, barcode=barcode, origin=origin, image=image, initial_stock=initial_stock, current_stock=initial_stock)
        db.session.add(product)
        # 先刷新会话获取自增的产品ID，解决product_id为None的报错
        db.session.flush()
        # 添加库存日志
        log = InventoryLog(product_id=product.id, change_type='初始库存', change_quantity=initial_stock, related_id=code, note='初始库存设置')
        db.session.add(log)
        db.session.commit()
        flash('产品添加成功！', 'success')
        return redirect(url_for('products'))
    products = Product.query.all()
    return render_template('product.html', products=products)

@app.route('/product/edit/<int:id>', methods=['GET', 'POST'])
@permission_required('product_manage')
def edit_product(id):
    product = Product.query.get_or_404(id)
    if request.method == 'POST':
        product.name = request.form['name']
        product.spec = request.form['spec']
        product.barcode = request.form['barcode']
        product.origin = request.form['origin']
        product.image = request.form.get('image', product.image)
        # 初始库存调整
        new_initial = int(request.form['initial_stock'])
        stock_change = new_initial - product.initial_stock
        product.initial_stock = new_initial
        product.current_stock += stock_change
        # 添加库存日志
        log = InventoryLog(product_id=product.id, change_type='初始库存调整', change_quantity=stock_change, related_id=product.code, note='初始库存调整')
        db.session.add(log)
        db.session.commit()
        flash('产品编辑成功！', 'success')
        return redirect(url_for('products'))
    return render_template('edit_product.html', product=product)

@app.route('/product/delete/<int:id>')
@permission_required('product_manage')
def delete_product(id):
    product = Product.query.get_or_404(id)
    # 检查是否有相关单据
    if product.orders or product.stockins or product.stockouts:
        flash('该产品已有相关单据，无法删除！', 'error')
        return redirect(url_for('products'))
    db.session.delete(product)
    db.session.commit()
    flash('产品删除成功！', 'success')
    return redirect(url_for('products'))

# 订单管理
@app.route('/orders', methods=['GET', 'POST'])
@permission_required('order_manage')
def orders():
    if request.method == 'POST':
        order_no = request.form['order_no']
        customer = request.form['customer']
        product_id = int(request.form['product_id'])
        quantity = int(request.form['quantity'])
        note = request.form['note']
        order_date = datetime.strptime(request.form['order_date'], '%Y-%m-%d') if request.form['order_date'] else datetime.now()
        # 检查订单编号是否已存在
        existing_order = Order.query.filter_by(order_no=order_no).first()
        if existing_order:
            flash('订单编号已存在！', 'error')
            return redirect(url_for('orders'))
        # 检查产品是否存在
        product = Product.query.get(product_id)
        if not product:
            flash('产品不存在！', 'error')
            return redirect(url_for('orders'))
        # 获取备货抵扣数据
        stockins_data = request.form.get('stockins_data')
        stockins_list = []
        if stockins_data:
            import json
            try:
                stockins_list = json.loads(stockins_data)
            except:
                pass
        # 创建订单
        order = Order(order_no=order_no, customer=customer, order_date=order_date, product_id=product_id, quantity=quantity, note=note, status='待备货')
        db.session.add(order)
        db.session.flush()
        # 处理备货抵扣
        total_deducted = 0
        if stockins_list:
            for item in stockins_list:
                stockin = StockIn.query.get(item['id'])
                if stockin:
                    deduct_qty = item['quantity']
                    remaining = stockin.quantity - sum(s.quantity for s in stockin.stockouts)
                    if deduct_qty > remaining:
                        deduct_qty = remaining
                    if deduct_qty > 0:
                        # 创建出货记录
                        stockout = StockOut(
                            stockout_no=f'STK-OUT-{datetime.now().strftime("%Y%m%d%H%M%S")}',
                            stockout_date=datetime.now(),
                            product_id=stockin.product_id,
                            quantity=deduct_qty,
                            order_id=order.id,
                            stockin_id=stockin.id,
                            note=f'订单抵扣：{order_no}'
                        )
                        db.session.add(stockout)
                        # 更新产品库存
                        stockin.product.current_stock -= deduct_qty
                        # 添加库存日志
                        log = InventoryLog(
                            product_id=stockin.product_id,
                            change_type='出货',
                            change_quantity=-deduct_qty,
                            related_id=stockout.stockout_no,
                            note=f'订单抵扣：{stockin.stockin_no}'
                        )
                        db.session.add(log)
                        total_deducted += deduct_qty
            # 如果抵扣数量达到订单数量，自动更新订单状态
            if total_deducted >= quantity:
                order.status = '已备货'
        db.session.commit()
        flash('订单添加成功！', 'success')
        return redirect(url_for('orders'))
    orders = Order.query.all()
    products = Product.query.all()
    return render_template('order.html', orders=orders, products=products)

# 获取可用备货列表API
@app.route('/api/available-stockins')
@permission_required('order_manage')
def available_stockins():
    stockins = StockIn.query.filter(StockIn.quantity > 0).all()
    result = []
    for stockin in stockins:
        remaining = stockin.quantity - sum(s.quantity for s in stockin.stockouts)
        result.append({
            'id': stockin.id,
            'stockin_no': stockin.stockin_no,
            'product_name': stockin.product.name,
            'remaining_quantity': remaining
        })
    return jsonify(result)

# 获取备货详情API
@app.route('/api/stockin-info/<int:stockin_id>')
@permission_required('order_manage')
def stockin_info(stockin_id):
    stockin = StockIn.query.get_or_404(stockin_id)
    remaining = stockin.quantity - sum(s.quantity for s in stockin.stockouts)
    return jsonify({
        'id': stockin.id,
        'stockin_no': stockin.stockin_no,
        'product_name': stockin.product.name,
        'remaining_quantity': remaining
    })

# 确认备货抵扣API
@app.route('/api/confirm-stockin-deduction', methods=['POST'])
@permission_required('order_manage')
def confirm_stockin_deduction():
    data = request.get_json()
    stockins = data.get('stockins', [])
    
    if not stockins:
        return jsonify({'success': False, 'message': '请选择备货SKU'})
    
    try:
        for item in stockins:
            stockin = StockIn.query.get(item['id'])
            if not stockin:
                return jsonify({'success': False, 'message': f"备货 {item['stockin_no']} 不存在"})
            
            quantity = item['quantity']
            if quantity <= 0:
                return jsonify({'success': False, 'message': '抵扣数量必须大于0'})
            
            remaining = stockin.quantity - sum(s.quantity for s in stockin.stockouts)
            if quantity > remaining:
                return jsonify({'success': False, 'message': f"备货 {stockin.stockin_no} 的剩余数量不足"})
            
            # 创建出货记录
            stockout = StockOut(
                stockout_no=f'STK-OUT-{datetime.now().strftime("%Y%m%d%H%M%S")}',
                stockout_date=datetime.now(),
                product_id=stockin.product_id,
                quantity=quantity,
                order_id=None,
                stockin_id=stockin.id,
                note=f'订单抵扣：{item.get("note", "")}'
            )
            db.session.add(stockout)
            
            # 更新产品库存
            stockin.product.current_stock -= quantity
            
            # 添加库存日志
            log = InventoryLog(
                product_id=stockin.product_id,
                change_type='出货',
                change_quantity=-quantity,
                related_id=stockout.stockout_no,
                note=f'订单抵扣：{stockin.stockin_no}'
            )
            db.session.add(log)
        
        db.session.commit()
        return jsonify({'success': True, 'message': '备货抵扣成功'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})

@app.route('/order/edit/<int:id>', methods=['GET', 'POST'])
@permission_required('order_manage')
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
        db.session.commit()
        flash('订单编辑成功！', 'success')
        return redirect(url_for('orders'))
    products = Product.query.all()
    return render_template('edit_order.html', order=order, products=products)

@app.route('/order/delete/<int:id>')
@permission_required('order_manage')
def delete_order(id):
    order = Order.query.get_or_404(id)
    # 已备货/已出货订单不能删除
    if order.status in ['已备货', '已出货']:
        flash('已备货或已出货的订单不能删除！', 'error')
        return redirect(url_for('orders'))
    db.session.delete(order)
    db.session.commit()
    flash('订单删除成功！', 'success')
    return redirect(url_for('orders'))

# 备货管理
@app.route('/stockins', methods=['GET', 'POST'])
@permission_required('stockin_manage')
def stockins():
    if request.method == 'POST':
        stockin_no = request.form['stockin_no']
        product_id = int(request.form['product_id'])
        quantity = int(request.form['quantity'])
        order_id = request.form['order_id'] if request.form['order_id'] else None
        note = request.form['note']
        stockin_date = datetime.strptime(request.form['stockin_date'], '%Y-%m-%d') if request.form['stockin_date'] else datetime.now()
        # 检查备货编号是否已存在
        existing_stockin = StockIn.query.filter_by(stockin_no=stockin_no).first()
        if existing_stockin:
            flash('备货编号已存在！', 'error')
            return redirect(url_for('stockins'))
        # 检查产品是否存在
        product = Product.query.get(product_id)
        if not product:
            flash('产品不存在！', 'error')
            return redirect(url_for('stockins'))
        # 检查订单是否存在
        order = None
        if order_id:
            order = Order.query.get(order_id)
            if not order:
                flash('订单不存在！', 'error')
                return redirect(url_for('stockins'))
            # 检查订单是否已备货
            if order.status == '已备货':
                flash('该订单已完成备货！', 'error')
                return redirect(url_for('stockins'))
            # 备货数量不能超过订单数量
            total_stocked = sum(s.quantity for s in order.stockins)
            if quantity > (order.quantity - total_stocked):
                flash('备货数量不能超过订单剩余待备货量！', 'error')
                return redirect(url_for('stockins'))
        # 创建备货记录
        stockin = StockIn(stockin_no=stockin_no, stockin_date=stockin_date, product_id=product_id, quantity=quantity, order_id=order_id, note=note)
        db.session.add(stockin)
        # 更新产品库存
        product.current_stock += quantity
        # 添加库存日志
        log = InventoryLog(product_id=product_id, change_type='备货', change_quantity=quantity, related_id=stockin_no, note=f'备货：{stockin_no}')
        db.session.add(log)
        # 更新订单状态
        if order:
            total_stocked = sum(s.quantity for s in order.stockins) + quantity
            if total_stocked >= order.quantity:
                order.status = '已备货'
            else:
                order.status = '部分备货'
        db.session.commit()
        flash('备货添加成功！', 'success')
        return redirect(url_for('stockins'))
    stockins = StockIn.query.all()
    products = Product.query.all()
    orders = Order.query.filter(Order.status.in_(['待备货', '部分备货', '待出货'])).all()
    return render_template('stockin.html', stockins=stockins, products=products, orders=orders)

# 出货管理
@app.route('/stockouts', methods=['GET', 'POST'])
@permission_required('stockout_manage')
def stockouts():
    if request.method == 'POST':
        stockout_no = request.form['stockout_no']
        order_id = int(request.form['order_id'])
        quantity = int(request.form['quantity'])
        stockin_id = request.form['stockin_id'] if request.form['stockin_id'] else None
        note = request.form['note']
        stockout_date = datetime.strptime(request.form['stockout_date'], '%Y-%m-%d') if request.form['stockout_date'] else datetime.now()
        # 检查出货编号是否已存在
        existing_stockout = StockOut.query.filter_by(stockout_no=stockout_no).first()
        if existing_stockout:
            flash('出货编号已存在！', 'error')
            return redirect(url_for('stockouts'))
        # 检查订单是否存在
        order = Order.query.get(order_id)
        if not order:
            flash('订单不存在！', 'error')
            return redirect(url_for('stockouts'))
        # 检查订单状态
        if order.status == '已出货':
            flash('该订单已完成出货！', 'error')
            return redirect(url_for('stockouts'))
        # 检查产品库存
        product = order.product
        if product.current_stock < quantity:
            flash('库存不足！', 'error')
            return redirect(url_for('stockouts'))
        # 检查备货是否存在
        stockin = None
        if stockin_id:
            stockin = StockIn.query.get(stockin_id)
            if not stockin:
                flash('备货记录不存在！', 'error')
                return redirect(url_for('stockouts'))
            # 检查备货是否关联该订单
            if stockin.order_id != order_id:
                flash('备货记录未关联该订单！', 'error')
                return redirect(url_for('stockouts'))
            # 检查备货剩余数量
            total_shipped_from_stockin = sum(s.quantity for s in stockin.stockouts)
            if quantity > (stockin.quantity - total_shipped_from_stockin):
                flash('出货数量不能超过备货剩余数量！', 'error')
                return redirect(url_for('stockouts'))
        # 检查出货数量是否超过订单剩余数量
        total_shipped = sum(s.quantity for s in order.stockouts)
        if quantity > (order.quantity - total_shipped):
            flash('出货数量不能超过订单剩余待出货量！', 'error')
            return redirect(url_for('stockouts'))
        # 创建出货记录
        stockout = StockOut(stockout_no=stockout_no, stockout_date=stockout_date, product_id=product.id, quantity=quantity, order_id=order_id, stockin_id=stockin_id, note=note)
        db.session.add(stockout)
        # 更新产品库存
        product.current_stock -= quantity
        # 添加库存日志
        log = InventoryLog(product_id=product.id, change_type='出货', change_quantity=-quantity, related_id=stockout_no, note=f'出货：{stockout_no}')
        db.session.add(log)
        # 更新订单状态
        total_shipped += quantity
        if total_shipped >= order.quantity:
            order.status = '已出货'
        else:
            order.status = '部分出货'
        db.session.commit()
        flash('出货添加成功！', 'success')
        return redirect(url_for('stockouts'))
    stockouts = StockOut.query.all()
    orders = Order.query.filter(Order.status.in_(['已备货', '部分备货', '待出货'])).all()
    # 预加载每个订单的备货记录
    order_stockins = {}
    for order in orders:
        order_stockins[order.id] = StockIn.query.filter_by(order_id=order.id).all()
    return render_template('stockout.html', stockouts=stockouts, orders=orders, order_stockins=order_stockins)

# 库存查询
@app.route('/inventory')
@permission_required('inventory_manage')
def inventory():
    products = Product.query.all()
    # 获取每个产品的库存流水
    product_logs = {}
    for product in products:
        logs = InventoryLog.query.filter_by(product_id=product.id).order_by(InventoryLog.change_date.desc()).all()
        product_logs[product.id] = logs
    return render_template('inventory.html', products=products, product_logs=product_logs)

# 报表统计
@app.route('/reports')
@permission_required('report_manage')
def reports():
    # 订单统计
    total_orders = Order.query.count()
    shipped_orders = Order.query.filter_by(status='已出货').count()
    pending_orders = Order.query.filter(Order.status.in_(['待出货', '部分备货', '已备货'])).count()
    # 备货统计
    total_stockin = db.session.query(db.func.sum(StockIn.quantity)).scalar() or 0
    # 出货统计
    total_stockout = db.session.query(db.func.sum(StockOut.quantity)).scalar() or 0
    # 库存统计
    total_stock = db.session.query(db.func.sum(Product.current_stock)).scalar() or 0
    # 按产品统计
    product_stats = []
    products = Product.query.all()
    for product in products:
        order_count = Order.query.filter_by(product_id=product.id).count()
        order_quantity = db.session.query(db.func.sum(Order.quantity)).filter_by(product_id=product.id).scalar() or 0
        stockin_quantity = db.session.query(db.func.sum(StockIn.quantity)).filter_by(product_id=product.id).scalar() or 0
        stockout_quantity = db.session.query(db.func.sum(StockOut.quantity)).filter_by(product_id=product.id).scalar() or 0
        product_stats.append({
            'name': product.name,
            'code': product.code,
            'order_count': order_count,
            'order_quantity': order_quantity,
            'stockin_quantity': stockin_quantity,
            'stockout_quantity': stockout_quantity,
            'current_stock': product.current_stock
        })
    return render_template('reports.html', 
                           total_orders=total_orders, 
                           shipped_orders=shipped_orders, 
                           pending_orders=pending_orders,
                           total_stockin=total_stockin,
                           total_stockout=total_stockout,
                           total_stock=total_stock,
                           product_stats=product_stats)

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
