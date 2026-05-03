"""
pytest配置文件 - 定义公共fixtures和测试配置
"""
import os
import sys
from datetime import datetime

import pytest

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# 在导入app之前设置环境变量,强制使用SQLite
os.environ['DB_TYPE'] = 'sqlite'
os.environ['SECRET_KEY'] = 'test-secret-key-for-testing-only'

from app import app, db


@pytest.fixture(scope='function')
def test_app():
    """创建测试应用实例 - 每个测试函数独立的数据库"""
    # 配置测试数据库 - 使用SQLite内存数据库
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False

    with app.app_context():
        # 创建所有表
        db.create_all()
        yield app
        # 清理:关闭会话
        db.session.close()
        # 删除所有表(对于SQLite内存数据库)
        try:
            db.drop_all()
        except Exception:
            pass  # 忽略删除错误


@pytest.fixture(scope='function')
def test_client(test_app):
    """创建测试客户端"""
    return test_app.test_client()


@pytest.fixture(scope='function')
def test_db(test_app):
    """创建测试数据库会话"""
    connection = db.engine.connect()
    transaction = connection.begin()

    options = {'bind': connection, 'binds': {}}
    session = db.create_scoped_session(options=options)
    db.session = session

    yield session

    transaction.rollback()
    connection.close()
    session.remove()


@pytest.fixture
def sample_product_data():
    """示例产品数据"""
    return {
        'name': '测试产品',
        'specification': '规格型号',
        'unit': '个',
        'category': '测试分类',
        'cost_price': 100.0,
        'selling_price': 150.0,
        'quantity': 100,
        'min_quantity': 10,
        'location': 'A-01-01',
        'remark': '测试备注'
    }


@pytest.fixture
def sample_order_data():
    """示例订单数据"""
    return {
        'order_number': f'ORD{datetime.now().strftime("%Y%m%d%H%M%S")}',
        'customer_name': '测试客户',
        'customer_phone': '13800138000',
        'customer_address': '测试地址',
        'total_amount': 1000.0,
        'status': 'pending',
        'remark': '测试订单'
    }


@pytest.fixture
def sample_user_data():
    """示例用户数据"""
    return {
        'username': 'testuser',
        'password': 'testpassword123',
        'role': 'user',
        'real_name': '测试用户',
        'phone': '13800138000'
    }


@pytest.fixture
def auth_header(test_client, sample_user_data):
    """认证头部fixture"""
    # 创建测试用户
    from app import User
    from werkzeug.security import generate_password_hash

    user = User(
        username=sample_user_data['username'],
        password=generate_password_hash(sample_user_data['password']),
        role=sample_user_data['role'],
        real_name=sample_user_data['real_name'],
        phone=sample_user_data['phone']
    )
    db.session.add(user)
    db.session.commit()

    # 登录获取token
    response = test_client.post('/api/login', json={
        'username': sample_user_data['username'],
        'password': sample_user_data['password']
    })

    token = response.json.get('token')
    return {'Authorization': f'Bearer {token}'}


# pytest钩子函数
def pytest_configure(config):
    """pytest配置钩子"""
    # 添加自定义标记
    config.addinivalue_line(
        "markers", "unit: mark test as a unit test"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as an integration test"
    )
    config.addinivalue_line(
        "markers", "functional: mark test as a functional test"
    )
    config.addinivalue_line(
        "markers", "boundary: mark test as a boundary test"
    )


def pytest_collection_modifyitems(config, items):
    """修改测试集合"""
    # 为没有标记的测试添加默认标记
    for item in items:
        if not list(item.iter_markers()):
            item.add_marker(pytest.mark.unit)
