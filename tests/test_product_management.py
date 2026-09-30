"""
产品管理模块功能测试
测试范围：产品CRUD、分类管理、规格管理、条码管理、边界条件

状态: 已摘除 flask_legacy 标记（CI 恢复收集本文件），但见下方警示。
"""
import os
import sys
import unittest
from datetime import datetime

# 已摘除 `flask_legacy` 标记：CI 不再用 `-m "not flask_legacy"` 把本文件整批反选。
# ⚠️ 必须如实说明：本文件**不 import 任何生产业务代码** —— 被测模型由文件内部自建
#    （Flask + Flask-SQLAlchemy + 内存 sqlite），所以用例通过只证明本文件自洽，
#    无法捕获 ERP 行为回归。另因 requirements/*.txt 无任何 Flask 条目，
#    CI 环境里本文件实际全部 skip，只有开发机残留 Flask 时才会真正执行。
#    跟踪项：按 FastAPI + SQLAlchemy 2.0 async 重写并改测真实模型（参考 tests/e2e_api/）。

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from flask import Flask
    from flask_sqlalchemy import SQLAlchemy
    HAS_FLASK = True
except ImportError:
    HAS_FLASK = False
    Flask = None
    SQLAlchemy = None


@unittest.skipIf(not HAS_FLASK, "Flask dependencies not available")
class ProductManagementTestCase(unittest.TestCase):
    """产品管理功能测试用例集"""

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
            specification = db.Column(db.String(50))
            unit = db.Column(db.String(20))
            price = db.Column(db.Float, default=0.0)
            current_stock = db.Column(db.Integer, default=0)
            min_stock = db.Column(db.Integer, default=10)
            category = db.Column(db.String(50))
            status = db.Column(db.String(20), default='active')
            create_time = db.Column(db.DateTime, default=datetime.now)

        cls.Product = Product

    @classmethod
    def _init_test_data(cls):
        """初始化测试数据"""
        products = [
            cls.Product(name='产品A', barcode='P001', specification='500g', unit='个', price=10.0, current_stock=100, category='食品'),
            cls.Product(name='产品B', barcode='P002', specification='1kg', unit='箱', price=20.0, current_stock=50, category='食品'),
            cls.Product(name='产品C', barcode='P003', specification='200ml', unit='瓶', price=5.0, current_stock=0, category='饮料'),
        ]
        cls.db.session.add_all(products)
        cls.db.session.commit()

    def setUp(self):
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    # ==================== 产品CRUD测试 ====================

    def test_01_create_product_success(self):
        """测试用例01: 成功创建产品"""
        print("\n[测试用例01] 成功创建产品")

        product = self.Product(
            name='新产品',
            barcode='NEW001',
            specification='100g',
            unit='袋',
            price=15.0,
            current_stock=200,
            category='零食'
        )
        self.db.session.add(product)
        self.db.session.commit()

        saved = self.Product.query.filter_by(barcode='NEW001').first()
        self.assertIsNotNone(saved)
        self.assertEqual(saved.name, '新产品')
        self.assertEqual(saved.price, 15.0)

    def test_02_create_product_with_duplicate_barcode(self):
        """测试用例02: 创建重复条码产品"""
        print("\n[测试用例02] 创建重复条码产品")

        product = self.Product(
            name='重复产品',
            barcode='P001',  # 已存在的条码
            price=10.0
        )
        self.db.session.add(product)

        with self.assertRaises(Exception):
            self.db.session.commit()

        self.db.session.rollback()

    def test_03_update_product_price(self):
        """测试用例03: 更新产品价格"""
        print("\n[测试用例03] 更新产品价格")

        product = self.Product.query.filter_by(barcode='P001').first()
        old_price = product.price
        product.price = 25.0
        self.db.session.commit()

        updated = self.Product.query.filter_by(barcode='P001').first()
        self.assertEqual(updated.price, 25.0)
        self.assertNotEqual(updated.price, old_price)

    def test_04_update_product_stock(self):
        """测试用例04: 更新产品库存"""
        print("\n[测试用例04] 更新产品库存")

        product = self.Product.query.filter_by(barcode='P001').first()
        product.current_stock = 150
        self.db.session.commit()

        updated = self.Product.query.filter_by(barcode='P001').first()
        self.assertEqual(updated.current_stock, 150)

    def test_05_delete_product(self):
        """测试用例05: 删除产品"""
        print("\n[测试用例05] 删除产品")

        # 创建临时产品
        product = self.Product(name='临时产品', barcode='TEMP001', price=10.0)
        self.db.session.add(product)
        self.db.session.commit()

        product_id = product.id

        # 删除产品
        self.db.session.delete(product)
        self.db.session.commit()

        # 验证删除
        deleted = self.Product.query.get(product_id)
        self.assertIsNone(deleted)

    def test_06_query_product_by_barcode(self):
        """测试用例06: 按条码查询产品"""
        print("\n[测试用例06] 按条码查询产品")

        product = self.Product.query.filter_by(barcode='P001').first()
        self.assertIsNotNone(product)
        self.assertEqual(product.name, '产品A')

    def test_07_query_product_by_category(self):
        """测试用例07: 按分类查询产品"""
        print("\n[测试用例07] 按分类查询产品")

        products = self.Product.query.filter_by(category='食品').all()
        self.assertGreater(len(products), 0)

        for p in products:
            self.assertEqual(p.category, '食品')

    def test_08_query_active_products(self):
        """测试用例08: 查询活跃产品"""
        print("\n[测试用例08] 查询活跃产品")

        products = self.Product.query.filter_by(status='active').all()
        self.assertGreater(len(products), 0)

    def test_09_product_stock_warning(self):
        """测试用例09: 产品库存预警"""
        print("\n[测试用例09] 产品库存预警")

        # 查询库存低于最低库存的产品
        low_stock_products = self.Product.query.filter(
            self.Product.current_stock < self.Product.min_stock
        ).all()

        self.assertGreater(len(low_stock_products), 0)

    def test_10_product_zero_stock(self):
        """测试用例10: 零库存产品"""
        print("\n[测试用例10] 零库存产品")

        products = self.Product.query.filter_by(current_stock=0).all()
        self.assertGreater(len(products), 0)

    # ==================== 分类管理测试 ====================

    def test_11_create_product_with_category(self):
        """测试用例11: 创建带分类的产品"""
        print("\n[测试用例11] 创建带分类的产品")

        product = self.Product(
            name='分类产品',
            barcode='CAT001',
            price=10.0,
            category='电子产品'
        )
        self.db.session.add(product)
        self.db.session.commit()

        saved = self.Product.query.filter_by(barcode='CAT001').first()
        self.assertEqual(saved.category, '电子产品')

    def test_12_query_all_categories(self):
        """测试用例12: 查询所有分类"""
        print("\n[测试用例12] 查询所有分类")

        from sqlalchemy import distinct
        categories = self.db.session.query(distinct(self.Product.category)).all()
        self.assertGreater(len(categories), 0)

    def test_13_update_product_category(self):
        """测试用例13: 更新产品分类"""
        print("\n[测试用例13] 更新产品分类")

        product = self.Product.query.filter_by(barcode='P001').first()
        product.category = '日用品'
        self.db.session.commit()

        updated = self.Product.query.filter_by(barcode='P001').first()
        self.assertEqual(updated.category, '日用品')

    # ==================== 规格管理测试 ====================

    def test_14_create_product_with_specification(self):
        """测试用例14: 创建带规格的产品"""
        print("\n[测试用例14] 创建带规格的产品")

        product = self.Product(
            name='规格产品',
            barcode='SPEC001',
            specification='500ml',
            price=10.0
        )
        self.db.session.add(product)
        self.db.session.commit()

        saved = self.Product.query.filter_by(barcode='SPEC001').first()
        self.assertEqual(saved.specification, '500ml')

    def test_15_update_product_specification(self):
        """测试用例15: 更新产品规格"""
        print("\n[测试用例15] 更新产品规格")

        product = self.Product.query.filter_by(barcode='P001').first()
        product.specification = '1L'
        self.db.session.commit()

        updated = self.Product.query.filter_by(barcode='P001').first()
        self.assertEqual(updated.specification, '1L')

    # ==================== 条码管理测试 ====================

    def test_16_unique_barcode_constraint(self):
        """测试用例16: 条码唯一性约束"""
        print("\n[测试用例16] 条码唯一性约束")

        # 创建第一个产品
        p1 = self.Product(name='产品1', barcode='UNIQUE001', price=10.0)
        self.db.session.add(p1)
        self.db.session.commit()

        # 尝试创建相同条码的产品
        p2 = self.Product(name='产品2', barcode='UNIQUE001', price=20.0)
        self.db.session.add(p2)

        with self.assertRaises(Exception):
            self.db.session.commit()

        self.db.session.rollback()

    def test_17_barcode_format_validation(self):
        """测试用例17: 条码格式验证"""
        print("\n[测试用例17] 条码格式验证")

        # 测试不同格式的条码
        barcodes = ['ABC123', '1234567890', 'P-001-2024']

        for i, barcode in enumerate(barcodes):
            product = self.Product(
                name=f'产品{i}',
                barcode=barcode,
                price=10.0
            )
            self.db.session.add(product)

        self.db.session.commit()

        # 验证所有条码都创建成功
        for barcode in barcodes:
            p = self.Product.query.filter_by(barcode=barcode).first()
            self.assertIsNotNone(p)

    # ==================== 边界条件测试 ====================

    def test_18_product_with_zero_price(self):
        """测试用例18: 零价格产品"""
        print("\n[测试用例18] 零价格产品")

        product = self.Product(
            name='免费产品',
            barcode='FREE001',
            price=0.0
        )
        self.db.session.add(product)
        self.db.session.commit()

        saved = self.Product.query.filter_by(barcode='FREE001').first()
        self.assertEqual(saved.price, 0.0)

    def test_19_product_with_negative_price(self):
        """测试用例19: 负价格产品"""
        print("\n[测试用例19] 负价格产品")

        product = self.Product(
            name='负价格产品',
            barcode='NEG001',
            price=-10.0
        )
        self.db.session.add(product)
        self.db.session.commit()

        # 数据库层面允许负价格，业务层面应该验证
        saved = self.Product.query.filter_by(barcode='NEG001').first()
        self.assertEqual(saved.price, -10.0)

    def test_20_product_with_long_name(self):
        """测试用例20: 长名称产品"""
        print("\n[测试用例20] 长名称产品")

        long_name = 'A' * 100  # 100个字符
        product = self.Product(
            name=long_name,
            barcode='LONG001',
            price=10.0
        )
        self.db.session.add(product)
        self.db.session.commit()

        saved = self.Product.query.filter_by(barcode='LONG001').first()
        self.assertEqual(len(saved.name), 100)

    def test_21_product_with_special_characters(self):
        """测试用例21: 特殊字符产品名称"""
        print("\n[测试用例21] 特殊字符产品名称")

        special_name = '产品@#$%^&*()测试'
        product = self.Product(
            name=special_name,
            barcode='SPECIAL001',
            price=10.0
        )
        self.db.session.add(product)
        self.db.session.commit()

        saved = self.Product.query.filter_by(barcode='SPECIAL001').first()
        self.assertEqual(saved.name, special_name)

    def test_22_product_status_change(self):
        """测试用例22: 产品状态变更"""
        print("\n[测试用例22] 产品状态变更")

        product = self.Product.query.filter_by(barcode='P001').first()

        # 状态流转: active -> inactive -> active
        product.status = 'inactive'
        self.db.session.commit()
        self.assertEqual(product.status, 'inactive')

        product.status = 'active'
        self.db.session.commit()
        self.assertEqual(product.status, 'active')

    def test_23_product_batch_create(self):
        """测试用例23: 批量创建产品"""
        print("\n[测试用例23] 批量创建产品")

        products = []
        for i in range(10):
            products.append(self.Product(
                name=f'批量产品{i}',
                barcode=f'BATCH{i:03d}',
                price=10.0 + i
            ))

        self.db.session.add_all(products)
        self.db.session.commit()

        # 验证批量创建成功
        count = self.Product.query.filter(self.Product.barcode.like('BATCH%')).count()
        self.assertEqual(count, 10)

    def test_24_product_search_by_name(self):
        """测试用例24: 按名称搜索产品"""
        print("\n[测试用例24] 按名称搜索产品")

        products = self.Product.query.filter(
            self.Product.name.like('%产品%')
        ).all()

        self.assertGreater(len(products), 0)

    def test_25_product_price_range_query(self):
        """测试用例25: 价格范围查询"""
        print("\n[测试用例25] 价格范围查询")

        products = self.Product.query.filter(
            self.Product.price.between(5.0, 20.0)
        ).all()

        self.assertGreater(len(products), 0)

        for p in products:
            self.assertGreaterEqual(p.price, 5.0)
            self.assertLessEqual(p.price, 20.0)


class ProductValidationTestCase(unittest.TestCase):
    """产品验证测试用例集"""

    def test_validate_product_name(self):
        """测试验证产品名称"""
        name = "测试产品"
        self.assertGreater(len(name), 0, "产品名称不能为空")

    def test_validate_barcode_format(self):
        """测试验证条码格式"""
        barcode = "P001"
        self.assertTrue(len(barcode) > 0, "条码不能为空")
        self.assertTrue(barcode.isalnum() or '-' in barcode, "条码格式应正确")

    def test_validate_price_positive(self):
        """测试验证价格"""
        price = 10.0
        self.assertGreater(price, 0, "价格应该大于0")

    def test_validate_stock_non_negative(self):
        """测试验证库存"""
        stock = 100
        self.assertGreaterEqual(stock, 0, "库存应该大于等于0")


if __name__ == '__main__':
    unittest.main(verbosity=2)
