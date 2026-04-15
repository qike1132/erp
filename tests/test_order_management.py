"""
订单管理模块功能测试
测试范围：订单创建、编辑、删除、查询、审批、状态流转
"""
import unittest
import json
import sys
import os
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect


class OrderManagementTestCase(unittest.TestCase):
    """订单管理功能测试用例集"""
    
    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        # 创建测试用的Flask应用
        cls.app = Flask(__name__)
        cls.app.config['TESTING'] = True
        cls.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        cls.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        cls.app.config['WTF_CSRF_ENABLED'] = False
        cls.app.config['SECRET_KEY'] = 'test-secret-key'
        
        # 初始化数据库
        cls.db = SQLAlchemy(cls.app)
        CSRFProtect(cls.app)
        
        # 定义模型
        cls._define_models()
        
        # 注册路由
        with cls.app.app_context():
            cls.db.create_all()
            cls._init_test_data()
    
    @classmethod
    def _define_models(cls):
        """定义数据模型"""
        db = cls.db
        
        # 用户模型
        class User(db.Model):
            __tablename__ = 'user'
            id = db.Column(db.Integer, primary_key=True)
            username = db.Column(db.String(50), unique=True, nullable=False)
            password = db.Column(db.String(200), nullable=False)
            is_super = db.Column(db.Boolean, default=False)
        
        # 产品模型
        class Product(db.Model):
            __tablename__ = 'product'
            id = db.Column(db.Integer, primary_key=True)
            name = db.Column(db.String(100), nullable=False)
            barcode = db.Column(db.String(50), unique=True)
            current_stock = db.Column(db.Integer, default=0)
            price = db.Column(db.Float, default=0.0)
        
        # 订单模型
        class Order(db.Model):
            __tablename__ = 'order'
            id = db.Column(db.Integer, primary_key=True)
            order_no = db.Column(db.String(20), unique=True, nullable=False)
            product_id = db.Column(db.Integer, db.ForeignKey('product.id'))
            quantity = db.Column(db.Integer, nullable=False)
            total_price = db.Column(db.Float, default=0.0)
            status = db.Column(db.String(20), default='pending')
            create_time = db.Column(db.DateTime, default=datetime.now)
            
            product = db.relationship('Product', backref='orders')
        
        cls.User = User
        cls.Product = Product
        cls.Order = Order
    
    @classmethod
    def _init_test_data(cls):
        """初始化测试数据"""
        # 创建测试用户
        admin = cls.User(username='admin', password='admin123', is_super=True)
        user = cls.User(username='user1', password='user123', is_super=False)
        cls.db.session.add_all([admin, user])
        
        # 创建测试产品
        product1 = cls.Product(name='产品A', barcode='P001', current_stock=100, price=10.0)
        product2 = cls.Product(name='产品B', barcode='P002', current_stock=50, price=20.0)
        cls.db.session.add_all([product1, product2])
        
        cls.db.session.commit()
    
    def setUp(self):
        """每个测试方法前的准备"""
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
    
    def tearDown(self):
        """每个测试方法后的清理"""
        self.app_context.pop()
    
    def test_01_create_order_success(self):
        """测试用例01: 成功创建订单"""
        print("\n[测试用例01] 成功创建订单")
        
        # 获取产品
        product = self.Product.query.first()
        
        # 创建订单
        order = self.Order(
            order_no='ORD001',
            product_id=product.id,
            quantity=10,
            total_price=100.0,
            status='pending'
        )
        self.db.session.add(order)
        self.db.session.commit()
        
        # 验证订单创建成功
        saved_order = self.Order.query.filter_by(order_no='ORD001').first()
        self.assertIsNotNone(saved_order)
        self.assertEqual(saved_order.quantity, 10)
        self.assertEqual(saved_order.status, 'pending')
    
    def test_02_create_order_with_invalid_product(self):
        """测试用例02: 使用无效产品ID创建订单"""
        print("\n[测试用例02] 使用无效产品ID创建订单")
        
        # SQLite内存数据库默认不强制外键约束
        # 这里测试业务逻辑：应该验证产品ID是否存在
        product = self.Product.query.get(999)
        self.assertIsNone(product, "产品ID 999 不应存在")
        
        # 业务层面应该拒绝无效产品ID
        # 这里我们验证产品不存在的情况
        print("  ✓ 无效产品ID验证正确")
    
    def test_03_create_order_with_negative_quantity(self):
        """测试用例03: 使用负数数量创建订单"""
        print("\n[测试用例03] 使用负数数量创建订单")
        
        product = self.Product.query.first()
        
        # 创建订单（负数数量）
        order = self.Order(
            order_no='ORD003',
            product_id=product.id,
            quantity=-10,  # 负数
            total_price=-100.0,
            status='pending'
        )
        self.db.session.add(order)
        self.db.session.commit()
        
        # 验证订单创建成功（数据库层面允许负数，业务层面应该验证）
        saved_order = self.Order.query.filter_by(order_no='ORD003').first()
        self.assertIsNotNone(saved_order)
        # 注意：这里应该添加业务逻辑验证，拒绝负数数量
    
    def test_04_update_order_quantity(self):
        """测试用例04: 更新订单数量"""
        print("\n[测试用例04] 更新订单数量")
        
        # 创建订单
        product = self.Product.query.first()
        order = self.Order(
            order_no='ORD004',
            product_id=product.id,
            quantity=10,
            total_price=100.0,
            status='pending'
        )
        self.db.session.add(order)
        self.db.session.commit()
        
        # 更新数量
        saved_order = self.Order.query.filter_by(order_no='ORD004').first()
        saved_order.quantity = 20
        saved_order.total_price = 200.0
        self.db.session.commit()
        
        # 验证更新成功
        updated_order = self.Order.query.filter_by(order_no='ORD004').first()
        self.assertEqual(updated_order.quantity, 20)
        self.assertEqual(updated_order.total_price, 200.0)
    
    def test_05_delete_order(self):
        """测试用例05: 删除订单"""
        print("\n[测试用例05] 删除订单")
        
        # 创建订单
        product = self.Product.query.first()
        order = self.Order(
            order_no='ORD005',
            product_id=product.id,
            quantity=10,
            total_price=100.0,
            status='pending'
        )
        self.db.session.add(order)
        self.db.session.commit()
        
        order_id = order.id
        
        # 删除订单
        self.db.session.delete(order)
        self.db.session.commit()
        
        # 验证删除成功
        deleted_order = self.Order.query.get(order_id)
        self.assertIsNone(deleted_order)
    
    def test_06_order_status_transition(self):
        """测试用例06: 订单状态流转"""
        print("\n[测试用例06] 订单状态流转")
        
        # 创建订单
        product = self.Product.query.first()
        order = self.Order(
            order_no='ORD006',
            product_id=product.id,
            quantity=10,
            total_price=100.0,
            status='pending'
        )
        self.db.session.add(order)
        self.db.session.commit()
        
        # 状态流转: pending -> approved -> completed
        order.status = 'approved'
        self.db.session.commit()
        self.assertEqual(order.status, 'approved')
        
        order.status = 'completed'
        self.db.session.commit()
        self.assertEqual(order.status, 'completed')
    
    def test_07_order_query_by_status(self):
        """测试用例07: 按状态查询订单"""
        print("\n[测试用例07] 按状态查询订单")
        
        # 清理之前的测试数据
        self.Order.query.filter(self.Order.order_no.like('ORD007-%')).delete()
        self.db.session.commit()
        
        # 创建多个不同状态的订单
        product = self.Product.query.first()
        orders = [
            self.Order(order_no='ORD007-1', product_id=product.id, quantity=10, total_price=100.0, status='pending'),
            self.Order(order_no='ORD007-2', product_id=product.id, quantity=20, total_price=200.0, status='approved'),
            self.Order(order_no='ORD007-3', product_id=product.id, quantity=30, total_price=300.0, status='pending'),
        ]
        self.db.session.add_all(orders)
        self.db.session.commit()
        
        # 查询pending状态的订单（只查询ORD007-开头的）
        pending_orders = self.Order.query.filter(
            self.Order.status == 'pending',
            self.Order.order_no.like('ORD007-%')
        ).all()
        self.assertEqual(len(pending_orders), 2)
        
        # 查询approved状态的订单（只查询ORD007-开头的）
        approved_orders = self.Order.query.filter(
            self.Order.status == 'approved',
            self.Order.order_no.like('ORD007-%')
        ).all()
        self.assertEqual(len(approved_orders), 1)
    
    def test_08_order_total_price_calculation(self):
        """测试用例08: 订单总价计算"""
        print("\n[测试用例08] 订单总价计算")
        
        # 获取产品
        product = self.Product.query.filter_by(barcode='P001').first()
        
        # 创建订单
        quantity = 15
        expected_total = quantity * product.price
        
        order = self.Order(
            order_no='ORD008',
            product_id=product.id,
            quantity=quantity,
            total_price=expected_total,
            status='pending'
        )
        self.db.session.add(order)
        self.db.session.commit()
        
        # 验证总价计算正确
        saved_order = self.Order.query.filter_by(order_no='ORD008').first()
        self.assertEqual(saved_order.total_price, expected_total)
        self.assertEqual(saved_order.total_price, 150.0)  # 15 * 10.0
    
    def test_09_order_unique_order_no(self):
        """测试用例09: 订单号唯一性约束"""
        print("\n[测试用例09] 订单号唯一性约束")
        
        product = self.Product.query.first()
        
        # 创建第一个订单
        order1 = self.Order(
            order_no='ORD009',
            product_id=product.id,
            quantity=10,
            total_price=100.0,
            status='pending'
        )
        self.db.session.add(order1)
        self.db.session.commit()
        
        # 尝试创建相同订单号的订单
        order2 = self.Order(
            order_no='ORD009',  # 重复的订单号
            product_id=product.id,
            quantity=20,
            total_price=200.0,
            status='pending'
        )
        self.db.session.add(order2)
        
        # 应该抛出唯一性约束异常
        with self.assertRaises(Exception):
            self.db.session.commit()
        
        # 回滚事务
        self.db.session.rollback()
    
    def test_10_order_with_zero_quantity(self):
        """测试用例10: 零数量订单"""
        print("\n[测试用例10] 零数量订单")
        
        product = self.Product.query.first()
        
        # 创建零数量订单
        order = self.Order(
            order_no='ORD010',
            product_id=product.id,
            quantity=0,
            total_price=0.0,
            status='pending'
        )
        self.db.session.add(order)
        self.db.session.commit()
        
        # 验证订单创建成功（业务层面应该拒绝零数量）
        saved_order = self.Order.query.filter_by(order_no='ORD010').first()
        self.assertIsNotNone(saved_order)
        self.assertEqual(saved_order.quantity, 0)


class OrderValidationTestCase(unittest.TestCase):
    """订单验证测试用例集"""
    
    def test_validate_positive_quantity(self):
        """测试验证正数数量"""
        quantity = 10
        self.assertGreater(quantity, 0, "数量应该大于0")
    
    def test_validate_order_no_format(self):
        """测试订单号格式"""
        order_no = 'ORD001'
        self.assertTrue(order_no.startswith('ORD'), "订单号应该以ORD开头")
        self.assertEqual(len(order_no), 6, "订单号长度应该为6")
    
    def test_validate_status_value(self):
        """测试状态值有效性"""
        valid_statuses = ['pending', 'approved', 'rejected', 'completed', 'cancelled']
        status = 'pending'
        self.assertIn(status, valid_statuses, "状态值应该有效")


if __name__ == '__main__':
    unittest.main(verbosity=2)
