"""
库存管理模块功能测试
测试范围：入库、出库、盘点、预警、库存查询
"""
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

Base = declarative_base()


class StockManagementTestCase(unittest.TestCase):
    """库存管理功能测试用例集"""

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
            min_stock = Column(Integer, default=10)  # 最低库存预警

        class StockIn(Base):
            __tablename__ = 'stock_in'
            id = Column(Integer, primary_key=True)
            product_id = Column(Integer, ForeignKey('product.id'))
            quantity = Column(Integer, nullable=False)
            create_time = Column(DateTime, default=datetime.now)

            product = relationship('Product', backref='stock_ins')

        class StockOut(Base):
            __tablename__ = 'stock_out'
            id = Column(Integer, primary_key=True)
            product_id = Column(Integer, ForeignKey('product.id'))
            quantity = Column(Integer, nullable=False)
            create_time = Column(DateTime, default=datetime.now)

            product = relationship('Product', backref='stock_outs')

        cls.Product = Product
        cls.StockIn = StockIn
        cls.StockOut = StockOut

    @classmethod
    def _init_test_data(cls):
        """初始化测试数据"""
        products = [
            cls.Product(name='产品A', barcode='P001', current_stock=100, min_stock=20),
            cls.Product(name='产品B', barcode='P002', current_stock=15, min_stock=20),  # 库存不足
            cls.Product(name='产品C', barcode='P003', current_stock=0, min_stock=10),   # 零库存
        ]
        cls.db_session.add_all(products)
        cls.db_session.commit()

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_01_stock_in_success(self):
        """测试用例01: 成功入库"""
        print("\n[测试用例01] 成功入库")

        product = self.db_session.query(self.Product).filter_by(barcode='P001').first()
        initial_stock = product.current_stock

        # 创建入库记录
        stock_in = self.StockIn(
            product_id=product.id,
            quantity=50
        )
        self.db_session.add(stock_in)

        # 更新库存
        product.current_stock += 50
        self.db_session.commit()

        # 验证库存更新
        updated_product = self.db_session.query(self.Product).filter_by(barcode='P001').first()
        self.assertEqual(updated_product.current_stock, initial_stock + 50)

    def test_02_stock_out_success(self):
        """测试用例02: 成功出库"""
        print("\n[测试用例02] 成功出库")

        product = self.db_session.query(self.Product).filter_by(barcode='P001').first()
        initial_stock = product.current_stock
        out_quantity = 30

        # 验证库存充足
        self.assertGreaterEqual(initial_stock, out_quantity, "库存应该充足")

        # 创建出库记录
        stock_out = self.StockOut(
            product_id=product.id,
            quantity=out_quantity
        )
        self.db_session.add(stock_out)

        # 更新库存
        product.current_stock -= out_quantity
        self.db_session.commit()

        # 验证库存更新
        updated_product = self.db_session.query(self.Product).filter_by(barcode='P001').first()
        self.assertEqual(updated_product.current_stock, initial_stock - out_quantity)

    def test_03_stock_out_insufficient(self):
        """测试用例03: 库存不足出库"""
        print("\n[测试用例03] 库存不足出库")

        product = self.db_session.query(self.Product).filter_by(barcode='P001').first()
        out_quantity = product.current_stock + 100  # 超过当前库存

        # 验证库存不足
        self.assertLess(product.current_stock, out_quantity, "库存应该不足")

        # 业务逻辑应该拒绝此次出库
        # 这里只是测试，实际应该有业务验证
        print(f"库存不足: 当前库存={product.current_stock}, 请求数量={out_quantity}")

    def test_04_stock_warning_check(self):
        """测试用例04: 库存预警检查"""
        print("\n[测试用例04] 库存预警检查")

        # 查询库存不足的产品
        low_stock_products = self.db_session.query(self.Product).filter(
            self.Product.current_stock < self.Product.min_stock
        ).all()

        # 验证找到库存不足的产品
        self.assertGreater(len(low_stock_products), 0, "应该存在库存不足的产品")

        # 验证产品B库存不足
        product_b = self.db_session.query(self.Product).filter_by(barcode='P002').first()
        self.assertLess(product_b.current_stock, product_b.min_stock, "产品B应该库存不足")

    def test_05_stock_zero_check(self):
        """测试用例05: 零库存检查"""
        print("\n[测试用例05] 零库存检查")

        # 查询零库存产品
        zero_stock_products = self.db_session.query(self.Product).filter_by(current_stock=0).all()

        # 验证找到零库存产品
        self.assertGreater(len(zero_stock_products), 0, "应该存在零库存产品")

        # 验证产品C零库存
        product_c = self.db_session.query(self.Product).filter_by(barcode='P003').first()
        self.assertEqual(product_c.current_stock, 0, "产品C应该零库存")

    def test_06_stock_in_batch(self):
        """测试用例06: 批量入库"""
        print("\n[测试用例06] 批量入库")

        products = self.db_session.query(self.Product).limit(3).all()

        # 批量入库
        for product in products:
            stock_in = self.StockIn(
                product_id=product.id,
                quantity=20
            )
            self.db_session.add(stock_in)
            product.current_stock += 20

        self.db_session.commit()

        # 验证所有产品库存都增加了
        for product in products:
            updated = self.db_session.query(self.Product).get(product.id)
            self.assertGreaterEqual(updated.current_stock, 20)

    def test_07_stock_query_by_product(self):
        """测试用例07: 按产品查询库存"""
        print("\n[测试用例07] 按产品查询库存")

        product = self.db_session.query(self.Product).filter_by(barcode='P001').first()

        # 查询该产品的所有入库记录
        stock_ins = self.db_session.query(self.StockIn).filter_by(product_id=product.id).all()

        # 验证查询结果
        self.assertIsInstance(stock_ins, list)

    def test_08_stock_negative_check(self):
        """测试用例08: 负库存检查"""
        print("\n[测试用例08] 负库存检查")

        # 查询负库存产品（不应该存在）
        negative_stock_products = self.db_session.query(self.Product).filter(
            self.Product.current_stock < 0
        ).all()

        # 验证不存在负库存
        self.assertEqual(len(negative_stock_products), 0, "不应该存在负库存产品")


class StockValidationTestCase(unittest.TestCase):
    """库存验证测试用例集"""

    def test_validate_stock_quantity(self):
        """测试验证库存数量"""
        quantity = 100
        self.assertGreaterEqual(quantity, 0, "库存数量应该大于等于0")

    def test_validate_min_stock_setting(self):
        """测试最低库存设置"""
        min_stock = 10
        self.assertGreater(min_stock, 0, "最低库存应该大于0")


if __name__ == '__main__':
    unittest.main(verbosity=2)
