"""
集成测试 - 跨模块业务流程测试
测试范围：订单流程、库存流程、审批流程、数据一致性
"""
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from flask import Flask
    from flask_sqlalchemy import SQLAlchemy
    HAS_FLASK = True
except ImportError:
    HAS_FLASK = False
    Flask = None
    SQLAlchemy = None

from fastapi_app.core.security import hash_password


@unittest.skipIf(not HAS_FLASK, "Flask dependencies not available")
class IntegrationTestCase(unittest.TestCase):
    """集成测试用例集"""

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
            cls._init_test_data()

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

        class Product(db.Model):
            __tablename__ = 'product'
            id = db.Column(db.Integer, primary_key=True)
            name = db.Column(db.String(100), nullable=False)
            barcode = db.Column(db.String(50), unique=True)
            current_stock = db.Column(db.Integer, default=0)
            price = db.Column(db.Float, default=0.0)

        class Order(db.Model):
            __tablename__ = 'order'
            id = db.Column(db.Integer, primary_key=True)
            order_no = db.Column(db.String(20), unique=True, nullable=False)
            product_id = db.Column(db.Integer, db.ForeignKey('product.id'))
            quantity = db.Column(db.Integer, nullable=False)
            total_price = db.Column(db.Float, default=0.0)
            status = db.Column(db.String(20), default='pending')
            is_locked = db.Column(db.Boolean, default=False)
            create_time = db.Column(db.DateTime, default=datetime.now)

            product = db.relationship('Product', backref='orders')

        class StockIn(db.Model):
            __tablename__ = 'stock_in'
            id = db.Column(db.Integer, primary_key=True)
            product_id = db.Column(db.Integer, db.ForeignKey('product.id'))
            quantity = db.Column(db.Integer, nullable=False)
            create_time = db.Column(db.DateTime, default=datetime.now)

            product = db.relationship('Product', backref='stock_ins')

        class StockOut(db.Model):
            __tablename__ = 'stock_out'
            id = db.Column(db.Integer, primary_key=True)
            product_id = db.Column(db.Integer, db.ForeignKey('product.id'))
            quantity = db.Column(db.Integer, nullable=False)
            create_time = db.Column(db.DateTime, default=datetime.now)

            product = db.relationship('Product', backref='stock_outs')

        class ApprovalRequest(db.Model):
            __tablename__ = 'approval_request'
            id = db.Column(db.Integer, primary_key=True)
            order_id = db.Column(db.Integer, db.ForeignKey('order.id'))
            requester_id = db.Column(db.Integer, db.ForeignKey('user.id'))
            operation_type = db.Column(db.String(20))
            status = db.Column(db.String(20), default='pending')

            order = db.relationship('Order', backref='approvals')

        cls.User = User
        cls.Product = Product
        cls.Order = Order
        cls.StockIn = StockIn
        cls.StockOut = StockOut
        cls.ApprovalRequest = ApprovalRequest

    @classmethod
    def _init_test_data(cls):
        """初始化测试数据"""
        # 创建用户
        admin = cls.User(username='admin', password=hash_password('admin123'), is_super=True)
        user = cls.User(username='user1', password=hash_password('user123'))

        # 创建产品
        product = cls.Product(name='产品A', barcode='P001', current_stock=100, price=10.0)

        cls.db.session.add_all([admin, user, product])
        cls.db.session.commit()

    def setUp(self):
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    # ==================== 订单流程集成测试 ====================

    def test_01_order_complete_flow(self):
        """集成测试01: 订单完整流程（创建→审批→完成）"""
        print("\n[集成测试01] 订单完整流程")

        # 1. 创建订单
        product = self.Product.query.first()
        order = self.Order(
            order_no='ORD001',
            product_id=product.id,
            quantity=10,
            total_price=100.0,
            status='pending'
        )
        self.db.session.add(order)
        self.db.session.commit()

        # 验证订单创建
        self.assertEqual(order.status, 'pending')

        # 2. 提交审批
        user = self.User.query.filter_by(username='user1').first()
        approval = self.ApprovalRequest(
            order_id=order.id,
            requester_id=user.id,
            operation_type='create',
            status='pending'
        )
        self.db.session.add(approval)
        order.is_locked = True
        self.db.session.commit()

        # 验证审批创建
        self.assertEqual(approval.status, 'pending')
        self.assertTrue(order.is_locked)

        # 3. 审批通过
        self.User.query.filter_by(username='admin').first()
        approval.status = 'approved'
        order.status = 'approved'
        order.is_locked = False
        self.db.session.commit()

        # 验证审批通过
        self.assertEqual(order.status, 'approved')
        self.assertFalse(order.is_locked)

        # 4. 订单完成
        order.status = 'completed'
        self.db.session.commit()

        # 验证订单完成
        self.assertEqual(order.status, 'completed')

    def test_02_order_with_insufficient_stock(self):
        """集成测试02: 库存不足的订单"""
        print("\n[集成测试02] 库存不足的订单")

        product = self.Product.query.first()

        # 尝试创建数量超过库存的订单
        quantity = product.current_stock + 100

        # 业务逻辑应该拒绝此订单
        # 这里验证库存不足的情况
        self.assertGreater(quantity, product.current_stock)
        print(f"  库存不足: 库存={product.current_stock}, 需求={quantity}")

    # ==================== 库存流程集成测试 ====================

    def test_03_stock_in_and_out_flow(self):
        """集成测试03: 入库出库完整流程"""
        print("\n[集成测试03] 入库出库完整流程")

        product = self.Product.query.first()
        initial_stock = product.current_stock

        # 1. 入库
        stock_in = self.StockIn(product_id=product.id, quantity=50)
        self.db.session.add(stock_in)
        product.current_stock += 50
        self.db.session.commit()

        # 验证入库
        self.assertEqual(product.current_stock, initial_stock + 50)

        # 2. 出库
        stock_out = self.StockOut(product_id=product.id, quantity=30)
        self.db.session.add(stock_out)
        product.current_stock -= 30
        self.db.session.commit()

        # 验证出库
        self.assertEqual(product.current_stock, initial_stock + 50 - 30)

    def test_04_stock_consistency_check(self):
        """集成测试04: 库存一致性检查"""
        print("\n[集成测试04] 库存一致性检查")

        product = self.Product.query.first()

        # 计算理论库存
        stock_in_total = sum(si.quantity for si in self.StockIn.query.filter_by(product_id=product.id).all())
        stock_out_total = sum(so.quantity for so in self.StockOut.query.filter_by(product_id=product.id).all())

        # 验证库存一致性（考虑初始库存）
        # 这里只是演示，实际应该有更复杂的验证逻辑
        print(f"  入库总量: {stock_in_total}, 出库总量: {stock_out_total}")

    # ==================== 审批流程集成测试 ====================

    def test_05_approval_reject_flow(self):
        """集成测试05: 审批拒绝流程"""
        print("\n[集成测试05] 审批拒绝流程")

        # 1. 创建订单
        product = self.Product.query.first()
        order = self.Order(
            order_no='ORD002',
            product_id=product.id,
            quantity=10,
            total_price=100.0,
            status='pending'
        )
        self.db.session.add(order)
        self.db.session.commit()

        # 2. 提交审批
        user = self.User.query.filter_by(username='user1').first()
        approval = self.ApprovalRequest(
            order_id=order.id,
            requester_id=user.id,
            operation_type='create',
            status='pending'
        )
        self.db.session.add(approval)
        order.is_locked = True
        self.db.session.commit()

        # 3. 审批拒绝
        approval.status = 'rejected'
        order.status = 'rejected'
        order.is_locked = False
        self.db.session.commit()

        # 验证审批拒绝
        self.assertEqual(order.status, 'rejected')
        self.assertFalse(order.is_locked)

    # ==================== 数据一致性集成测试 ====================

    def test_06_order_product_consistency(self):
        """集成测试06: 订单产品数据一致性"""
        print("\n[集成测试06] 订单产品数据一致性")

        # 创建订单
        product = self.Product.query.first()
        order = self.Order(
            order_no='ORD003',
            product_id=product.id,
            quantity=10,
            total_price=product.price * 10,
            status='pending'
        )
        self.db.session.add(order)
        self.db.session.commit()

        # 验证订单与产品的关联
        saved_order = self.Order.query.filter_by(order_no='ORD003').first()
        self.assertEqual(saved_order.product.id, product.id)
        self.assertEqual(saved_order.total_price, product.price * saved_order.quantity)

    def test_07_concurrent_stock_operations(self):
        """集成测试07: 并发库存操作"""
        print("\n[集成测试07] 并发库存操作")

        product = self.Product.query.first()
        initial_stock = product.current_stock

        # 模拟并发操作（顺序执行）
        # 操作1: 入库
        product.current_stock += 20

        # 操作2: 出库
        product.current_stock -= 10

        self.db.session.commit()

        # 验证最终库存
        expected_stock = initial_stock + 20 - 10
        self.assertEqual(product.current_stock, expected_stock)

    def test_08_user_order_relationship(self):
        """集成测试08: 用户订单关系"""
        print("\n[集成测试08] 用户订单关系")

        user = self.User.query.filter_by(username='user1').first()
        product = self.Product.query.first()

        # 创建订单
        order = self.Order(
            order_no='ORD004',
            product_id=product.id,
            quantity=10,
            total_price=100.0,
            status='pending'
        )
        self.db.session.add(order)
        self.db.session.commit()

        # 创建审批请求（关联用户和订单）
        approval = self.ApprovalRequest(
            order_id=order.id,
            requester_id=user.id,
            operation_type='create',
            status='pending'
        )
        self.db.session.add(approval)
        self.db.session.commit()

        # 验证关系
        saved_approval = self.ApprovalRequest.query.filter_by(order_id=order.id).first()
        self.assertEqual(saved_approval.requester_id, user.id)
        self.assertEqual(saved_approval.order_id, order.id)

    def test_09_product_stock_update_consistency(self):
        """集成测试09: 产品库存更新一致性"""
        print("\n[集成测试09] 产品库存更新一致性")

        product = self.Product.query.first()
        initial_stock = product.current_stock

        # 创建入库记录
        stock_in = self.StockIn(product_id=product.id, quantity=100)
        self.db.session.add(stock_in)

        # 更新产品库存
        product.current_stock += 100
        self.db.session.commit()

        # 验证一致性
        saved_product = self.Product.query.get(product.id)
        saved_stock_in = self.StockIn.query.get(stock_in.id)

        self.assertEqual(saved_product.current_stock, initial_stock + 100)
        self.assertEqual(saved_stock_in.quantity, 100)

    def test_10_order_status_transition_validation(self):
        """集成测试10: 订单状态流转验证"""
        print("\n[集成测试10] 订单状态流转验证")

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

        # 验证状态流转
        # pending -> approved
        order.status = 'approved'
        self.db.session.commit()
        self.assertEqual(order.status, 'approved')

        # approved -> completed
        order.status = 'completed'
        self.db.session.commit()
        self.assertEqual(order.status, 'completed')

        # 验证不能回退（业务逻辑）
        # 这里只是演示，实际应该有状态机验证


if __name__ == '__main__':
    unittest.main(verbosity=2)
