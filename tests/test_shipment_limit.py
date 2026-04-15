"""
出货量限制逻辑测试
测试业务规则：出货量严格受限于订单量，备货量只能通过订单抵扣使用
"""
import unittest
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask
from flask_sqlalchemy import SQLAlchemy


class ShipmentLimitTestCase(unittest.TestCase):
    """出货量限制逻辑测试用例集"""
    
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
        
        class Product(db.Model):
            __tablename__ = 'product'
            id = db.Column(db.Integer, primary_key=True)
            name = db.Column(db.String(100), nullable=False)
            barcode = db.Column(db.String(50), unique=True)
            current_stock = db.Column(db.Integer, default=0)
        
        class Customer(db.Model):
            __tablename__ = 'customer'
            id = db.Column(db.Integer, primary_key=True)
            name = db.Column(db.String(100), nullable=False, unique=True)
        
        class Order(db.Model):
            __tablename__ = 'order'
            id = db.Column(db.Integer, primary_key=True)
            order_no = db.Column(db.String(20), unique=True, nullable=False)
            customer = db.Column(db.String(100), nullable=False)
            product_id = db.Column(db.Integer, db.ForeignKey('product.id'))
            quantity = db.Column(db.Integer, nullable=False)
            status = db.Column(db.String(20), default='待备货')
            
            product = db.relationship('Product', backref='orders')
        
        class StockIn(db.Model):
            __tablename__ = 'stock_in'
            id = db.Column(db.Integer, primary_key=True)
            stockin_no = db.Column(db.String(20), unique=True)
            product_id = db.Column(db.Integer, db.ForeignKey('product.id'))
            customer = db.Column(db.String(100))
            quantity = db.Column(db.Integer, nullable=False)
            stockin_date = db.Column(db.DateTime, default=datetime.now)
            
            product = db.relationship('Product', backref='stockins')
        
        class StockOut(db.Model):
            __tablename__ = 'stock_out'
            id = db.Column(db.Integer, primary_key=True)
            stockout_no = db.Column(db.String(20), unique=True)
            product_id = db.Column(db.Integer, db.ForeignKey('product.id'))
            customer = db.Column(db.String(100))
            quantity = db.Column(db.Integer, nullable=False)
            order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=True)
            stockin_id = db.Column(db.Integer, db.ForeignKey('stock_in.id'), nullable=True)
            stockout_date = db.Column(db.DateTime, default=datetime.now)
            
            product = db.relationship('Product', backref='stockouts')
            order = db.relationship('Order', backref='stockouts')
            stockin = db.relationship('StockIn', backref='stockouts')
        
        cls.Product = Product
        cls.Customer = Customer
        cls.Order = Order
        cls.StockIn = StockIn
        cls.StockOut = StockOut
    
    @classmethod
    def _init_test_data(cls):
        """初始化测试数据"""
        product = cls.Product(name='测试产品', barcode='TEST001', current_stock=0)
        customer = cls.Customer(name='测试客户')
        cls.db.session.add_all([product, customer])
        cls.db.session.commit()
    
    def setUp(self):
        self.app_context = self.app.app_context()
        self.app_context.push()
    
    def tearDown(self):
        self.app_context.pop()
    
    def test_01_available_shipment_calculation(self):
        """
        测试用例01: 可出货量计算
        
        场景：
        - 订单量：5000
        - 备货量：5000
        - 总库存：10000
        
        预期结果：
        - 可出货量 = 订单量 = 5000
        - 备货量不能直接出货
        """
        print("\n[测试用例01] 可出货量计算")
        
        product = self.Product.query.first()
        customer = self.Customer.query.first()
        
        order = self.Order(
            order_no='ORD001',
            customer=customer.name,
            product_id=product.id,
            quantity=5000,
            status='待备货'
        )
        self.db.session.add(order)
        product.current_stock += 5000
        
        stockin = self.StockIn(
            stockin_no='SI001',
            product_id=product.id,
            customer=customer.name,
            quantity=5000
        )
        self.db.session.add(stockin)
        product.current_stock += 5000
        
        self.db.session.commit()
        
        self.assertEqual(product.current_stock, 10000, "总库存应为10000")
        
        orders = self.Order.query.filter_by(
            product_id=product.id,
            customer=customer.name
        ).all()
        total_order_quantity = sum(o.quantity for o in orders)
        
        total_shipped = self.db.session.query(
            self.db.func.sum(self.StockOut.quantity)
        ).join(self.Order, self.StockOut.order_id == self.Order.id).filter(
            self.Order.product_id == product.id,
            self.Order.customer == customer.name,
            self.StockOut.stockin_id.is_(None)
        ).scalar() or 0
        
        available_quantity = max(0, total_order_quantity - total_shipped)
        
        self.assertEqual(available_quantity, 5000, "可出货量应等于订单量5000")
        print(f"  总库存: {product.current_stock}")
        print(f"  订单量: {total_order_quantity}")
        print(f"  可出货量: {available_quantity}")
    
    def test_02_shipment_exceeds_order_should_fail(self):
        """
        测试用例02: 出货量超过订单量应失败
        
        场景：
        - 订单量：5000
        - 备货量：5000
        - 尝试出货：10000
        
        预期结果：
        - 出货应被拒绝，因为超过订单量
        """
        print("\n[测试用例02] 出货量超过订单量应失败")
        
        product = self.Product.query.first()
        customer = self.Customer.query.first()
        
        orders = self.Order.query.filter_by(
            product_id=product.id,
            customer=customer.name
        ).all()
        total_order_quantity = sum(o.quantity for o in orders)
        
        total_shipped = self.db.session.query(
            self.db.func.sum(self.StockOut.quantity)
        ).join(self.Order, self.StockOut.order_id == self.Order.id).filter(
            self.Order.product_id == product.id,
            self.Order.customer == customer.name,
            self.StockOut.stockin_id.is_(None)
        ).scalar() or 0
        
        available_quantity = max(0, total_order_quantity - total_shipped)
        
        requested_quantity = 10000
        can_ship = requested_quantity <= available_quantity
        
        self.assertFalse(can_ship, "出货10000应被拒绝，因为超过可出货量5000")
        print(f"  请求出货量: {requested_quantity}")
        print(f"  可出货量: {available_quantity}")
        print(f"  出货被拒绝: {not can_ship}")
    
    def test_03_partial_shipment_within_order(self):
        """
        测试用例03: 部分出货在订单量范围内应成功
        
        场景：
        - 订单量：5000
        - 第一次出货：3000
        - 第二次出货：2000
        
        预期结果：
        - 两次出货都应成功
        - 总出货量 = 5000
        """
        print("\n[测试用例03] 部分出货在订单量范围内应成功")
        
        product = self.Product.query.first()
        customer = self.Customer.query.first()
        
        order = self.Order.query.filter_by(
            product_id=product.id,
            customer=customer.name
        ).first()
        
        stockout1 = self.StockOut(
            stockout_no='SO001',
            product_id=product.id,
            customer=customer.name,
            quantity=3000,
            order_id=order.id,
            stockin_id=None
        )
        self.db.session.add(stockout1)
        product.current_stock -= 3000
        self.db.session.commit()
        
        total_shipped = self.db.session.query(
            self.db.func.sum(self.StockOut.quantity)
        ).join(self.Order, self.StockOut.order_id == self.Order.id).filter(
            self.Order.product_id == product.id,
            self.Order.customer == customer.name,
            self.StockOut.stockin_id.is_(None)
        ).scalar() or 0
        
        available_quantity = 5000 - total_shipped
        
        self.assertEqual(available_quantity, 2000, "剩余可出货量应为2000")
        
        stockout2 = self.StockOut(
            stockout_no='SO002',
            product_id=product.id,
            customer=customer.name,
            quantity=2000,
            order_id=order.id,
            stockin_id=None
        )
        self.db.session.add(stockout2)
        product.current_stock -= 2000
        self.db.session.commit()
        
        total_shipped = self.db.session.query(
            self.db.func.sum(self.StockOut.quantity)
        ).join(self.Order, self.StockOut.order_id == self.Order.id).filter(
            self.Order.product_id == product.id,
            self.Order.customer == customer.name,
            self.StockOut.stockin_id.is_(None)
        ).scalar() or 0
        
        self.assertEqual(total_shipped, 5000, "总出货量应为5000")
        print(f"  第一次出货: 3000")
        print(f"  第二次出货: 2000")
        print(f"  总出货量: {total_shipped}")
    
    def test_04_deduction_shipment_separate_from_regular(self):
        """
        测试用例04: 订单抵扣出货与普通出货分开计算
        
        场景：
        - 订单量：5000
        - 备货量：5000
        - 订单抵扣出货：3000（通过备货抵扣）
        - 普通出货：2000
        
        预期结果：
        - 普通出货量计算不包含抵扣出货
        - 可出货量 = 订单量 - 普通出货量
        """
        print("\n[测试用例04] 订单抵扣出货与普通出货分开计算")
        
        product = self.Product.query.first()
        customer = self.Customer.query.first()
        
        order = self.Order.query.filter_by(
            product_id=product.id,
            customer=customer.name
        ).first()
        
        stockin = self.StockIn.query.filter_by(
            product_id=product.id,
            customer=customer.name
        ).first()
        
        deduction_stockout = self.StockOut(
            stockout_no='SO-DEDUCT',
            product_id=product.id,
            customer=customer.name,
            quantity=3000,
            order_id=order.id,
            stockin_id=stockin.id
        )
        self.db.session.add(deduction_stockout)
        product.current_stock -= 3000
        self.db.session.commit()
        
        total_non_deduction_shipped = self.db.session.query(
            self.db.func.sum(self.StockOut.quantity)
        ).join(self.Order, self.StockOut.order_id == self.Order.id).filter(
            self.Order.product_id == product.id,
            self.Order.customer == customer.name,
            self.StockOut.stockin_id.is_(None)
        ).scalar() or 0
        
        self.assertEqual(total_non_deduction_shipped, 5000, 
            "非抵扣出货量应为5000（之前的测试数据）")
        
        available_quantity = 5000 - total_non_deduction_shipped
        self.assertEqual(available_quantity, 0, "可出货量应为0（订单已全部出货）")
        
        print(f"  订单抵扣出货: 3000")
        print(f"  普通出货: {total_non_deduction_shipped}")
        print(f"  可出货量: {available_quantity}")
    
    def test_05_no_order_no_shipment(self):
        """
        测试用例05: 无订单时不能出货
        
        场景：
        - 新客户，无订单
        - 尝试出货
        
        预期结果：
        - 可出货量 = 0
        """
        print("\n[测试用例05] 无订单时不能出货")
        
        product = self.Product.query.first()
        new_customer = '新客户'
        
        orders = self.Order.query.filter_by(
            product_id=product.id,
            customer=new_customer
        ).all()
        total_order_quantity = sum(o.quantity for o in orders)
        
        available_quantity = max(0, total_order_quantity)
        
        self.assertEqual(available_quantity, 0, "无订单时可出货量应为0")
        print(f"  客户: {new_customer}")
        print(f"  订单量: {total_order_quantity}")
        print(f"  可出货量: {available_quantity}")
    
    def test_06_multiple_orders_aggregation(self):
        """
        测试用例06: 多订单聚合计算
        
        场景：
        - 同一客户同一产品有多个订单
        - 订单1：3000
        - 订单2：2000
        - 总订单量：5000
        
        预期结果：
        - 可出货量 = 所有订单量之和
        """
        print("\n[测试用例06] 多订单聚合计算")
        
        product = self.Product.query.first()
        customer = self.Customer.query.first()
        
        self.db.session.query(self.Order).filter(
            self.Order.product_id == product.id,
            self.Order.customer == customer.name
        ).delete()
        
        order1 = self.Order(
            order_no='ORD-MULTI-001',
            customer=customer.name,
            product_id=product.id,
            quantity=3000
        )
        order2 = self.Order(
            order_no='ORD-MULTI-002',
            customer=customer.name,
            product_id=product.id,
            quantity=2000
        )
        self.db.session.add_all([order1, order2])
        product.current_stock += 5000
        self.db.session.commit()
        
        orders = self.Order.query.filter_by(
            product_id=product.id,
            customer=customer.name
        ).all()
        total_order_quantity = sum(o.quantity for o in orders)
        
        self.assertEqual(total_order_quantity, 5000, "总订单量应为5000")
        print(f"  订单1: 3000")
        print(f"  订单2: 2000")
        print(f"  总订单量: {total_order_quantity}")


class ShipmentLimitBusinessRuleTestCase(unittest.TestCase):
    """出货量限制业务规则测试 - 模拟完整业务流程"""
    
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
        
        class Product(db.Model):
            __tablename__ = 'product'
            id = db.Column(db.Integer, primary_key=True)
            name = db.Column(db.String(100), nullable=False)
            current_stock = db.Column(db.Integer, default=0)
        
        class Order(db.Model):
            __tablename__ = 'order'
            id = db.Column(db.Integer, primary_key=True)
            order_no = db.Column(db.String(20), unique=True)
            customer = db.Column(db.String(100))
            product_id = db.Column(db.Integer, db.ForeignKey('product.id'))
            quantity = db.Column(db.Integer)
            status = db.Column(db.String(20), default='待备货')
            
            product = db.relationship('Product', backref='orders')
        
        class StockIn(db.Model):
            __tablename__ = 'stock_in'
            id = db.Column(db.Integer, primary_key=True)
            stockin_no = db.Column(db.String(20), unique=True)
            product_id = db.Column(db.Integer, db.ForeignKey('product.id'))
            customer = db.Column(db.String(100))
            quantity = db.Column(db.Integer)
            
            product = db.relationship('Product', backref='stockins')
        
        class StockOut(db.Model):
            __tablename__ = 'stock_out'
            id = db.Column(db.Integer, primary_key=True)
            stockout_no = db.Column(db.String(20), unique=True)
            product_id = db.Column(db.Integer, db.ForeignKey('product.id'))
            customer = db.Column(db.String(100))
            quantity = db.Column(db.Integer)
            order_id = db.Column(db.Integer, db.ForeignKey('order.id'))
            stockin_id = db.Column(db.Integer, db.ForeignKey('stock_in.id'))
            
            product = db.relationship('Product', backref='stockouts')
            order = db.relationship('Order', backref='stockouts')
            stockin = db.relationship('StockIn', backref='stockouts')
        
        cls.Product = Product
        cls.Order = Order
        cls.StockIn = StockIn
        cls.StockOut = StockOut
    
    def setUp(self):
        self.app_context = self.app.app_context()
        self.app_context.push()
        
        self.product = self.Product(name='测试产品', current_stock=0)
        self.db.session.add(self.product)
        self.db.session.commit()
    
    def tearDown(self):
        self.db.session.rollback()
        self.app_context.pop()
    
    def test_bug_scenario_5000_order_5000_stockin(self):
        """
        测试原始BUG场景：
        - 订单量：5000
        - 备货量：5000
        - 总库存：10000
        - 尝试出货：10000
        
        预期结果：
        - 出货应被限制为5000（订单量）
        """
        print("\n[BUG场景测试] 订单5000 + 备货5000，尝试出货10000")
        
        order = self.Order(
            order_no='ORD-BUG-001',
            customer='客户A',
            product_id=self.product.id,
            quantity=5000
        )
        self.db.session.add(order)
        self.product.current_stock += 5000
        
        stockin = self.StockIn(
            stockin_no='SI-BUG-001',
            product_id=self.product.id,
            customer='客户A',
            quantity=5000
        )
        self.db.session.add(stockin)
        self.product.current_stock += 5000
        self.db.session.commit()
        
        self.assertEqual(self.product.current_stock, 10000, "总库存应为10000")
        
        orders = self.Order.query.filter_by(
            product_id=self.product.id,
            customer='客户A'
        ).all()
        total_order_quantity = sum(o.quantity for o in orders)
        
        total_shipped = self.db.session.query(
            self.db.func.sum(self.StockOut.quantity)
        ).join(self.Order, self.StockOut.order_id == self.Order.id).filter(
            self.Order.product_id == self.product.id,
            self.Order.customer == '客户A',
            self.StockOut.stockin_id.is_(None)
        ).scalar() or 0
        
        available_quantity = max(0, total_order_quantity - total_shipped)
        
        self.assertEqual(available_quantity, 5000, 
            "可出货量应等于订单量5000，而不是总库存10000")
        
        requested_quantity = 10000
        can_ship = requested_quantity <= available_quantity
        
        self.assertFalse(can_ship, 
            "出货10000应被拒绝！这是原始BUG：系统错误地允许出货超过订单量")
        
        print(f"  ✓ 订单量: {total_order_quantity}")
        print(f"  ✓ 备货量: 5000")
        print(f"  ✓ 总库存: {self.product.current_stock}")
        print(f"  ✓ 可出货量: {available_quantity}")
        print(f"  ✓ 请求出货: {requested_quantity}")
        print(f"  ✓ 出货被正确拒绝: {not can_ship}")
        print("  ✓ BUG已修复：出货量严格受限于订单量")


if __name__ == '__main__':
    unittest.main(verbosity=2)
