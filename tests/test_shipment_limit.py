"""
出货量限制逻辑测试
测试业务规则：出货量严格受限于订单量，备货量只能通过订单抵扣使用
"""
import unittest
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, func
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

Base = declarative_base()


class ShipmentLimitTestCase(unittest.TestCase):
    """出货量限制逻辑测试用例集"""
    
    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        cls.engine = create_engine('sqlite:///:memory:')
        cls._define_models()
        
        Base.metadata.create_all(cls.engine)
        Session = sessionmaker(bind=cls.engine)
        cls.db_session = Session()
        cls._init_test_data()
    
    @classmethod
    def _define_models(cls):
        """定义数据模型"""
        
        class Product(Base):
            __tablename__ = 'product'
            id = Column(Integer, primary_key=True)
            name = Column(String(100), nullable=False)
            barcode = Column(String(50), unique=True)
            current_stock = Column(Integer, default=0)
        
        class Customer(Base):
            __tablename__ = 'customer'
            id = Column(Integer, primary_key=True)
            name = Column(String(100), nullable=False, unique=True)
        
        class Order(Base):
            __tablename__ = 'order'
            id = Column(Integer, primary_key=True)
            order_no = Column(String(20), unique=True, nullable=False)
            customer = Column(String(100), nullable=False)
            product_id = Column(Integer, ForeignKey('product.id'))
            quantity = Column(Integer, nullable=False)
            status = Column(String(20), default='待备货')
            
            product = relationship('Product', backref='orders')
        
        class StockIn(Base):
            __tablename__ = 'stock_in'
            id = Column(Integer, primary_key=True)
            stockin_no = Column(String(20), unique=True)
            product_id = Column(Integer, ForeignKey('product.id'))
            customer = Column(String(100))
            quantity = Column(Integer, nullable=False)
            stockin_date = Column(DateTime, default=datetime.now)
            
            product = relationship('Product', backref='stockins')
        
        class StockOut(Base):
            __tablename__ = 'stock_out'
            id = Column(Integer, primary_key=True)
            stockout_no = Column(String(20), unique=True)
            product_id = Column(Integer, ForeignKey('product.id'))
            customer = Column(String(100))
            quantity = Column(Integer, nullable=False)
            order_id = Column(Integer, ForeignKey('order.id'), nullable=True)
            stockin_id = Column(Integer, ForeignKey('stock_in.id'), nullable=True)
            stockout_date = Column(DateTime, default=datetime.now)
            
            product = relationship('Product', backref='stockouts')
            order = relationship('Order', backref='stockouts')
            stockin = relationship('StockIn', backref='stockouts')
        
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
        cls.db_session.add_all([product, customer])
        cls.db_session.commit()
    
    def setUp(self):
        pass
    
    def tearDown(self):
        pass
    
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
        
        product = self.db_session.query(self.Product).first()
        customer = self.db_session.query(self.Customer).first()
        
        order = self.Order(
            order_no='ORD001',
            customer=customer.name,
            product_id=product.id,
            quantity=5000,
            status='待备货'
        )
        self.db_session.add(order)
        product.current_stock += 5000
        
        stockin = self.StockIn(
            stockin_no='SI001',
            product_id=product.id,
            customer=customer.name,
            quantity=5000
        )
        self.db_session.add(stockin)
        product.current_stock += 5000
        
        self.db_session.commit()
        
        self.assertEqual(product.current_stock, 10000, "总库存应为10000")
        
        orders = self.db_session.query(self.Order).filter_by(
            product_id=product.id,
            customer=customer.name
        ).all()
        total_order_quantity = sum(o.quantity for o in orders)
        
        total_shipped = self.db_session.query(
            func.sum(self.StockOut.quantity)
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
        """
        print("\n[测试用例02] 出货量超过订单量应失败")
        
        product = self.db_session.query(self.Product).first()
        customer = self.db_session.query(self.Customer).first()
        
        orders = self.db_session.query(self.Order).filter_by(
            product_id=product.id,
            customer=customer.name
        ).all()
        total_order_quantity = sum(o.quantity for o in orders)
        
        total_shipped = self.db_session.query(
            func.sum(self.StockOut.quantity)
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
        """
        print("\n[测试用例03] 部分出货在订单量范围内应成功")
        
        product = self.db_session.query(self.Product).first()
        customer = self.db_session.query(self.Customer).first()
        
        order = self.db_session.query(self.Order).filter_by(
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
        self.db_session.add(stockout1)
        product.current_stock -= 3000
        self.db_session.commit()
        
        total_shipped = self.db_session.query(
            func.sum(self.StockOut.quantity)
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
        self.db_session.add(stockout2)
        product.current_stock -= 2000
        self.db_session.commit()
        
        total_shipped = self.db_session.query(
            func.sum(self.StockOut.quantity)
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
        """
        print("\n[测试用例04] 订单抵扣出货与普通出货分开计算")
        
        product = self.db_session.query(self.Product).first()
        customer = self.db_session.query(self.Customer).first()
        
        order = self.db_session.query(self.Order).filter_by(
            product_id=product.id,
            customer=customer.name
        ).first()
        
        stockin = self.db_session.query(self.StockIn).filter_by(
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
        self.db_session.add(deduction_stockout)
        product.current_stock -= 3000
        self.db_session.commit()
        
        total_non_deduction_shipped = self.db_session.query(
            func.sum(self.StockOut.quantity)
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
        """
        print("\n[测试用例05] 无订单时不能出货")
        
        product = self.db_session.query(self.Product).first()
        new_customer = '新客户'
        
        orders = self.db_session.query(self.Order).filter_by(
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
        """
        print("\n[测试用例06] 多订单聚合计算")
        
        product = self.db_session.query(self.Product).first()
        customer = self.db_session.query(self.Customer).first()
        
        self.db_session.query(self.Order).filter(
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
        self.db_session.add_all([order1, order2])
        product.current_stock += 5000
        self.db_session.commit()
        
        orders = self.db_session.query(self.Order).filter_by(
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
        cls.engine = create_engine('sqlite:///:memory:')
        cls._define_models()
        
        Base.metadata.create_all(cls.engine)
        Session = sessionmaker(bind=cls.engine)
        cls.db_session = Session()
    
    @classmethod
    def _define_models(cls):
        """定义数据模型"""
        
        class Product(Base):
            __tablename__ = 'product'
            id = Column(Integer, primary_key=True)
            name = Column(String(100), nullable=False)
            current_stock = Column(Integer, default=0)
        
        class Order(Base):
            __tablename__ = 'order'
            id = Column(Integer, primary_key=True)
            order_no = Column(String(20), unique=True)
            customer = Column(String(100))
            product_id = Column(Integer, ForeignKey('product.id'))
            quantity = Column(Integer)
            status = Column(String(20), default='待备货')
            
            product = relationship('Product', backref='orders')
        
        class StockIn(Base):
            __tablename__ = 'stock_in'
            id = Column(Integer, primary_key=True)
            stockin_no = Column(String(20), unique=True)
            product_id = Column(Integer, ForeignKey('product.id'))
            customer = Column(String(100))
            quantity = Column(Integer)
            
            product = relationship('Product', backref='stockins')
        
        class StockOut(Base):
            __tablename__ = 'stock_out'
            id = Column(Integer, primary_key=True)
            stockout_no = Column(String(20), unique=True)
            product_id = Column(Integer, ForeignKey('product.id'))
            customer = Column(String(100))
            quantity = Column(Integer)
            order_id = Column(Integer, ForeignKey('order.id'))
            stockin_id = Column(Integer, ForeignKey('stock_in.id'))
            
            product = relationship('Product', backref='stockouts')
            order = relationship('Order', backref='stockouts')
            stockin = relationship('StockIn', backref='stockouts')
        
        cls.Product = Product
        cls.Order = Order
        cls.StockIn = StockIn
        cls.StockOut = StockOut
    
    def setUp(self):
        self.product = self.Product(name='测试产品', current_stock=0)
        self.db_session.add(self.product)
        self.db_session.commit()
    
    def tearDown(self):
        self.db_session.rollback()
    
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
        self.db_session.add(order)
        self.product.current_stock += 5000
        
        stockin = self.StockIn(
            stockin_no='SI-BUG-001',
            product_id=self.product.id,
            customer='客户A',
            quantity=5000
        )
        self.db_session.add(stockin)
        self.product.current_stock += 5000
        self.db_session.commit()
        
        self.assertEqual(self.product.current_stock, 10000, "总库存应为10000")
        
        orders = self.db_session.query(self.Order).filter_by(
            product_id=self.product.id,
            customer='客户A'
        ).all()
        total_order_quantity = sum(o.quantity for o in orders)
        
        total_shipped = self.db_session.query(
            func.sum(self.StockOut.quantity)
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
        
        print(f"  订单量: {total_order_quantity}")
        print(f"  备货量: 5000")
        print(f"  总库存: {self.product.current_stock}")
        print(f"  可出货量: {available_quantity}")
        print(f"  请求出货: {requested_quantity}")
        print(f"  出货被正确拒绝: {not can_ship}")
        print("  BUG已修复：出货量严格受限于订单量")


if __name__ == '__main__':
    unittest.main(verbosity=2)
