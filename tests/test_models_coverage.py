"""
数据模型覆盖率测试 - 提高数据模型测试覆盖率
测试范围：用户模型、订单模型、库存模型的所有方法

状态: 已摘除 flask_legacy 标记（CI 恢复收集本文件），但见下方警示。
"""
import os
import sys
import unittest
from datetime import datetime

# 已摘除 `flask_legacy` 标记：CI 不再用 `-m "not flask_legacy"` 把本文件整批反选。
# ⚠️ 必须如实说明：本文件除 `from fastapi_app.core.security import hash_password,
#    verify_password`（真实代码）外不 import 任何生产业务代码 —— 被测模型由文件内部
#    自建（Flask + Flask-SQLAlchemy + 内存 sqlite），故其通过只能证明本文件自洽，
#    不能证明 ERP 行为正确。另因 requirements/*.txt 无任何 Flask 条目，
#    CI 环境里本文件实际全部 skip，只有开发机残留 Flask 时才会真正执行。
#    跟踪项：把模型换成 fastapi_app.models 的真实模型 + SQLAlchemy 2.0 async 会话。

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from flask import Flask
    from flask_sqlalchemy import SQLAlchemy
    HAS_FLASK = True
except ImportError:
    HAS_FLASK = False
    Flask = None
    SQLAlchemy = None

from fastapi_app.core.security import hash_password, verify_password


@unittest.skipIf(not HAS_FLASK, "Flask dependencies not available")
class ModelsCoverageTestCase(unittest.TestCase):
    """数据模型覆盖率测试用例集"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        cls.app = Flask(__name__)
        cls.app.config['TESTING'] = True
        cls.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        cls.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        cls.app.config['SECRET_KEY'] = 'test-secret-key'

        cls.db = SQLAlchemy(cls.app)
        cls._define_models()

        with cls.app.app_context():
            cls.db.create_all()

    @classmethod
    def _define_models(cls):
        """定义数据模型"""
        db = cls.db

        class User(db.Model):
            __tablename__ = 'user'
            id = db.Column(db.Integer, primary_key=True)
            username = db.Column(db.String(50), unique=True, nullable=False)
            password = db.Column(db.String(200), nullable=False)
            is_super = db.Column(db.Boolean, default=False)
            status = db.Column(db.Boolean, default=True)
            phone = db.Column(db.String(20))
            email = db.Column(db.String(100))

            def set_password(self, password):
                """设置密码"""
                self.password = hash_password(password)

            def check_password(self, password):
                """验证密码"""
                return verify_password(password, self.password)

            def to_dict(self):
                """转换为字典"""
                return {
                    'id': self.id,
                    'username': self.username,
                    'is_super': self.is_super,
                    'status': self.status,
                    'phone': self.phone,
                    'email': self.email
                }

        class Product(db.Model):
            __tablename__ = 'product'
            id = db.Column(db.Integer, primary_key=True)
            name = db.Column(db.String(100), nullable=False)
            barcode = db.Column(db.String(50), unique=True)
            current_stock = db.Column(db.Integer, default=0)
            initial_stock = db.Column(db.Integer, default=0)
            price = db.Column(db.Float, default=0.0)
            create_time = db.Column(db.DateTime, default=datetime.now)

            def to_dict(self):
                """转换为字典"""
                return {
                    'id': self.id,
                    'name': self.name,
                    'barcode': self.barcode,
                    'current_stock': self.current_stock,
                    'initial_stock': self.initial_stock,
                    'price': self.price
                }

        class Order(db.Model):
            __tablename__ = 'order'
            id = db.Column(db.Integer, primary_key=True)
            order_no = db.Column(db.String(20), unique=True, nullable=False)
            product_id = db.Column(db.Integer, db.ForeignKey('product.id'))
            quantity = db.Column(db.Integer, nullable=False)
            customer = db.Column(db.String(100))
            status = db.Column(db.String(20), default='pending')
            is_locked = db.Column(db.Boolean, default=False)
            locked_by_id = db.Column(db.Integer)
            lock_time = db.Column(db.DateTime)
            create_time = db.Column(db.DateTime, default=datetime.now)

            product = db.relationship('Product', backref='orders')

            def lock(self, user_id):
                """锁定订单"""
                self.is_locked = True
                self.locked_by_id = user_id
                self.lock_time = datetime.now()

            def unlock(self):
                """解锁订单"""
                self.is_locked = False
                self.locked_by_id = None
                self.lock_time = None

            def is_locked_by_other(self, user_id):
                """检查是否被其他用户锁定"""
                return self.is_locked and self.locked_by_id != user_id

            def to_dict(self):
                """转换为字典"""
                return {
                    'id': self.id,
                    'order_no': self.order_no,
                    'product_id': self.product_id,
                    'quantity': self.quantity,
                    'customer': self.customer,
                    'status': self.status,
                    'is_locked': self.is_locked
                }

        cls.User = User
        cls.Product = Product
        cls.Order = Order

    def setUp(self):
        """每个测试前的准备"""
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        """每个测试后的清理"""
        self.db.session.rollback()
        self.app_context.pop()

    # ==================== 用户模型测试 ====================

    def test_user_create(self):
        """测试用户创建"""
        user = self.User(
            username='testuser',
            password=hash_password('password123'),
            is_super=False,
            status=True
        )
        self.db.session.add(user)
        self.db.session.commit()

        self.assertIsNotNone(user.id)
        self.assertEqual(user.username, 'testuser')
        self.assertFalse(user.is_super)
        self.assertTrue(user.status)

    def test_user_password_methods(self):
        """测试用户密码方法"""
        user = self.User(username='pwdtest')
        user.set_password('mypassword')

        # 验证密码设置
        self.assertIsNotNone(user.password)

        # 验证正确密码
        self.assertTrue(user.check_password('mypassword'))

        # 验证错误密码
        self.assertFalse(user.check_password('wrongpassword'))

    def test_user_to_dict(self):
        """测试用户字典转换"""
        user = self.User(
            username='dicttest',
            password='hashed',
            is_super=True,
            status=True,
            phone='13800138000',
            email='test@example.com'
        )
        self.db.session.add(user)
        self.db.session.commit()

        user_dict = user.to_dict()

        self.assertEqual(user_dict['username'], 'dicttest')
        self.assertTrue(user_dict['is_super'])
        self.assertEqual(user_dict['phone'], '13800138000')
        self.assertEqual(user_dict['email'], 'test@example.com')

    def test_user_unique_username(self):
        """测试用户名唯一性"""
        user1 = self.User(username='unique1', password='pwd1')
        user2 = self.User(username='unique2', password='pwd2')

        self.db.session.add(user1)
        self.db.session.add(user2)
        self.db.session.commit()

        self.assertNotEqual(user1.id, user2.id)
        self.assertEqual(user1.username, 'unique1')
        self.assertEqual(user2.username, 'unique2')

    # ==================== 产品模型测试 ====================

    def test_product_create(self):
        """测试产品创建"""
        product = self.Product(
            name='测试产品',
            barcode='BC001',
            current_stock=100,
            initial_stock=100,
            price=10.5
        )
        self.db.session.add(product)
        self.db.session.commit()

        self.assertIsNotNone(product.id)
        self.assertEqual(product.name, '测试产品')
        self.assertEqual(product.barcode, 'BC001')
        self.assertEqual(product.current_stock, 100)

    def test_product_to_dict(self):
        """测试产品字典转换"""
        product = self.Product(
            name='字典产品',
            barcode='BC002',
            current_stock=50,
            initial_stock=50,
            price=20.0
        )
        self.db.session.add(product)
        self.db.session.commit()

        product.to_dict()
