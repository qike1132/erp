"""
ERP系统单元测试
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from app.models import Order, Product, User


class BaseTestCase(unittest.TestCase):
    """基础测试类"""

    def setUp(self):
        """测试前准备"""
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        self.app = app.test_client()

        with app.app_context():
            db.create_all()
            # 创建测试用户
            user = User(username='testuser', password='testpass', is_super=True)
            db.session.add(user)
            db.session.commit()

    def tearDown(self):
        """测试后清理"""
        with app.app_context():
            db.session.remove()
            db.drop_all()


class ProductTestCase(BaseTestCase):
    """产品模型测试"""

    def test_create_product(self):
        """测试创建产品"""
        with app.app_context():
            product = Product(
                name='测试产品',
                barcode='123456789',
                initial_stock=100,
                current_stock=100
            )
            db.session.add(product)
            db.session.commit()

            self.assertIsNotNone(product.id)
            self.assertEqual(product.name, '测试产品')
            self.assertEqual(product.current_stock, 100)

    def test_product_to_dict(self):
        """测试产品转字典"""
        with app.app_context():
            product = Product(
                name='测试产品',
                barcode='123456789',
                initial_stock=100,
                current_stock=100
            )
            db.session.add(product)
            db.session.commit()

            product_dict = product.to_dict()
            self.assertIn('id', product_dict)
            self.assertIn('name', product_dict)
            self.assertEqual(product_dict['name'], '测试产品')


class OrderTestCase(BaseTestCase):
    """订单模型测试"""

    def test_create_order(self):
        """测试创建订单"""
        with app.app_context():
            # 先创建产品
            product = Product(name='测试产品', current_stock=100)
            db.session.add(product)
            db.session.commit()

            # 创建订单
            order = Order(
                order_no='PO-20260321-001',
                customer='测试客户',
                product_id=product.id,
                quantity=10
            )
            db.session.add(order)
            db.session.commit()

            self.assertIsNotNone(order.id)
            self.assertEqual(order.status, '待备货')
            self.assertEqual(order.quantity, 10)


class UserTestCase(BaseTestCase):
    """用户模型测试"""

    def test_create_user(self):
        """测试创建用户"""
        with app.app_context():
            from werkzeug.security import generate_password_hash

            user = User(
                username='newuser',
                password=generate_password_hash('password123'),
                is_super=False
            )
            db.session.add(user)
            db.session.commit()

            self.assertIsNotNone(user.id)
            self.assertEqual(user.username, 'newuser')
            self.assertFalse(user.is_super)

    def test_user_login(self):
        """测试用户登录"""
        response = self.app.post('/login', data={
            'username': 'testuser',
            'password': 'testpass'
        }, follow_redirects=True)

        self.assertEqual(response.status_code, 200)


class APITestCase(BaseTestCase):
    """API接口测试"""

    def test_product_search_api(self):
        """测试产品搜索API"""
        # 先登录
        self.app.post('/login', data={
            'username': 'testuser',
            'password': 'testpass'
        })

        response = self.app.get('/api/product-search?q=测试')
        self.assertEqual(response.status_code, 200)


if __name__ == '__main__':
    unittest.main()
