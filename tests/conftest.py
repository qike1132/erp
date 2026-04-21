"""
测试配置文件
提供测试fixtures和通用配置
"""
import pytest
import os
import sys

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from flask import Flask
    from app import create_app, db
    from app.models import (
        User, Product, Order, StockIn, StockOut,
        InventoryLog, Customer, Permission, ApprovalRequest
    )
    HAS_FLASK = True
except ImportError:
    HAS_FLASK = False
    create_app = None
    db = None
    User = None
    Product = None
    Order = None
    StockIn = None
    StockOut = None
    InventoryLog = None
    Customer = None
    Permission = None
    ApprovalRequest = None

from fastapi_app.core.security import hash_password


@pytest.fixture(scope='session')
def app():
    """创建测试应用"""
    if not HAS_FLASK:
        pytest.skip("Flask dependencies not available")
    test_app = create_app('testing')
    
    with test_app.app_context():
        db.create_all()
        yield test_app
        db.session.remove()
        db.drop_all()


@pytest.fixture(scope='function')
def client(app):
    """创建测试客户端"""
    return app.test_client()


@pytest.fixture(scope='function')
def db_session(app):
    """数据库会话"""
    with app.app_context():
        connection = db.engine.connect()
        transaction = connection.begin()
        
        yield db.session
        
        # 回滚事务
        transaction.rollback()
        connection.close()
        db.session.remove()


@pytest.fixture(scope='function')
def admin_user(db_session):
    """创建管理员用户"""
    # 检查是否已存在
    admin = User.query.filter_by(username='admin').first()
    if not admin:
        admin = User(
            username='admin',
            password=hash_password('admin123'),
            is_super=True,
            status=True
        )
        db_session.add(admin)
        db_session.commit()
    return admin


@pytest.fixture(scope='function')
def normal_user(db_session):
    """创建普通用户"""
    # 检查是否已存在
    user = User.query.filter_by(username='testuser').first()
    if not user:
        user = User(
            username='testuser',
            password=hash_password('test123'),
            is_super=False,
            status=True
        )
        db_session.add(user)
        db_session.commit()
    return user


@pytest.fixture(scope='function')
def test_product(db_session):
    """创建测试产品"""
    product = Product(
        name='测试产品',
        barcode='TEST001',
        current_stock=100,
        initial_stock=100
    )
    db_session.add(product)
    db_session.commit()
    return product


@pytest.fixture(scope='function')
def test_products(db_session):
    """创建多个测试产品"""
    products = []
    for i in range(1, 6):
        product = Product(
            name=f'测试产品{i}',
            barcode=f'TEST00{i}',
            current_stock=100 * i,
            initial_stock=100 * i
        )
        db_session.add(product)
        products.append(product)
    db_session.commit()
    return products


@pytest.fixture(scope='function')
def test_customer(db_session):
    """创建测试客户"""
    customer = Customer(
        name='测试客户',
        contact='张三',
        phone='13800138000',
        address='测试地址',
        status=True
    )
    db_session.add(customer)
    db_session.commit()
    return customer


@pytest.fixture(scope='function')
def test_order(db_session, test_product, test_customer):
    """创建测试订单"""
    from datetime import datetime
    order = Order(
        order_no='ORD-TEST-001',
        product_id=test_product.id,
        customer=test_customer.name,
        quantity=10,
        order_date=datetime.now(),
        status='待备货'
    )
    db_session.add(order)
    db_session.commit()
    return order


@pytest.fixture(scope='function')
def test_stockin(db_session, test_product, test_customer):
    """创建测试入库记录"""
    from datetime import datetime
    stockin = StockIn(
        stockin_no='SI-TEST-001',
        product_id=test_product.id,
        customer=test_customer.name,
        quantity=50,
        stockin_date=datetime.now()
    )
    db_session.add(stockin)
    db_session.commit()
    return stockin


@pytest.fixture(scope='function')
def test_stockout(db_session, test_product, test_customer):
    """创建测试出库记录"""
    from datetime import datetime
    stockout = StockOut(
        stockout_no='SO-TEST-001',
        product_id=test_product.id,
        customer=test_customer.name,
        quantity=20,
        stockout_date=datetime.now()
    )
    db_session.add(stockout)
    db_session.commit()
    return stockout


@pytest.fixture(scope='function')
def test_permission(db_session):
    """创建测试权限"""
    permission = Permission(
        name='test_permission',
        description='测试权限',
        code='test_view'
    )
    db_session.add(permission)
    db_session.commit()
    return permission


@pytest.fixture(scope='function')
def logged_in_client(client, admin_user):
    """已登录的测试客户端"""
    with client.session_transaction() as sess:
        sess['user_id'] = admin_user.id
        sess['username'] = admin_user.username
        sess['is_super'] = admin_user.is_super
    return client


@pytest.fixture(scope='function')
def auth_headers(admin_user):
    """认证头"""
    return {
        'Content-Type': 'application/json',
        'X-User-Id': str(admin_user.id)
    }


def create_test_data(db_session):
    """创建完整测试数据集"""
    # 创建用户
    admin = User(
        username='admin',
        password=hash_password('admin123'),
        is_super=True,
        status=True
    )
    db_session.add(admin)
    
    # 创建客户
    customer = Customer(
        name='测试客户A',
        contact='张三',
        phone='13800138000',
        status=True
    )
    db_session.add(customer)
    
    # 创建产品
    for i in range(1, 11):
        product = Product(
            name=f'产品{i}',
            barcode=f'BC{i:04d}',
            current_stock=100,
            price=10.0 * i
        )
        db_session.add(product)
    
    db_session.commit()
    return admin, customer
