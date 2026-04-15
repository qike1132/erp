"""
边界条件测试
测试数值边界、空值、超长输入、特殊字符等场景
"""
import pytest
from app import app, db
from app.models import Product, Order, StockIn, StockOut, User
from werkzeug.security import generate_password_hash


@pytest.mark.boundary
class TestNumericBoundaries:
    """数值边界测试"""
    
    def test_product_stock_zero(self, test_app):
        """测试库存为零"""
        with test_app.app_context():
            product = Product(name='零库存产品', current_stock=0)
            db.session.add(product)
            db.session.commit()
            
            assert product.current_stock == 0
    
    def test_product_stock_negative(self, test_app):
        """测试负库存"""
        with test_app.app_context():
            product = Product(name='负库存产品', current_stock=-10)
            db.session.add(product)
            db.session.commit()
            
            # 系统应该允许负库存(表示欠货)
            assert product.current_stock == -10
    
    def test_product_stock_large_value(self, test_app):
        """测试大库存值"""
        with test_app.app_context():
            large_stock = 999999999
            product = Product(name='大库存产品', current_stock=large_stock)
            db.session.add(product)
            db.session.commit()
            
            assert product.current_stock == large_stock
    
    def test_order_quantity_zero(self, test_app):
        """测试订单数量为零"""
        with test_app.app_context():
            product = Product(name='零数量订单产品')
            db.session.add(product)
            db.session.commit()
            
            order = Order(
                order_no='ORD-ZERO-QTY',
                customer='零数量客户',
                product_id=product.id,
                quantity=0
            )
            db.session.add(order)
            db.session.commit()
            
            assert order.quantity == 0
    
    def test_order_quantity_large(self, test_app):
        """测试大订单数量"""
        with test_app.app_context():
            product = Product(name='大数量订单产品')
            db.session.add(product)
            db.session.commit()
            
            large_quantity = 999999
            order = Order(
                order_no='ORD-LARGE-QTY',
                customer='大数量客户',
                product_id=product.id,
                quantity=large_quantity
            )
            db.session.add(order)
            db.session.commit()
            
            assert order.quantity == large_quantity


@pytest.mark.boundary
class TestEmptyAndNoneValues:
    """空值和None测试"""
    
    def test_product_empty_name(self, test_app):
        """测试产品名称为空"""
        with test_app.app_context():
            product = Product(name='')
            db.session.add(product)
            # SQLite允许空字符串,只有NOT NULL约束才会阻止None
            db.session.commit()
            assert product.name == ''
    
    def test_product_none_barcode(self, test_app):
        """测试条码为None"""
        with test_app.app_context():
            product = Product(name='无条码产品', barcode=None)
            db.session.add(product)
            db.session.commit()
            
            # 条码可以为None
            assert product.barcode is None
    
    def test_order_empty_customer(self, test_app):
        """测试订单客户为空"""
        with test_app.app_context():
            product = Product(name='空客户订单产品')
            db.session.add(product)
            db.session.commit()
            
            order = Order(
                order_no='ORD-EMPTY-CUSTOMER',
                customer='',
                product_id=product.id,
                quantity=10
            )
            db.session.add(order)
            # SQLite允许空字符串
            db.session.commit()
            assert order.customer == ''
    
    def test_stockout_null_customer(self, test_app):
        """测试出货客户为Null"""
        with test_app.app_context():
            product = Product(name='Null客户出货产品')
            db.session.add(product)
            db.session.commit()
            
            stockout = StockOut(
                stockout_no='SO-NULL-CUSTOMER',
                product_id=product.id,
                quantity=10,
                customer=None
            )
            db.session.add(stockout)
            db.session.commit()
            
            # 出货客户可以为None
            assert stockout.customer is None


@pytest.mark.boundary
class TestStringLengthBoundaries:
    """字符串长度边界测试"""
    
    def test_product_long_name(self, test_app):
        """测试超长产品名称"""
        with test_app.app_context():
            long_name = 'A' * 200  # 超过100字符限制
            product = Product(name=long_name)
            db.session.add(product)
            # SQLite不会自动截断,需要应用层验证
            # 这里测试数据库是否能存储长字符串
            try:
                db.session.commit()
                # 如果成功,说明数据库允许长字符串
                assert len(product.name) == 200
            except Exception:
                # 如果失败,说明有长度限制
                db.session.rollback()
    
    def test_product_max_name_length(self, test_app):
        """测试产品名称最大长度"""
        with test_app.app_context():
            max_name = 'A' * 100  # 正好100字符
            product = Product(name=max_name)
            db.session.add(product)
            db.session.commit()
            
            assert len(product.name) == 100
    
    def test_product_long_barcode(self, test_app):
        """测试超长条码"""
        with test_app.app_context():
            long_barcode = '6' * 100  # 超过50字符限制
            product = Product(name='长条码产品', barcode=long_barcode)
            db.session.add(product)
            # SQLite不会自动截断,需要应用层验证
            try:
                db.session.commit()
                assert len(product.barcode) == 100
            except Exception:
                db.session.rollback()
    
    def test_order_long_note(self, test_app):
        """测试订单超长备注"""
        with test_app.app_context():
            product = Product(name='长备注订单产品')
            db.session.add(product)
            db.session.commit()
            
            long_note = 'N' * 10000  # 非常长的备注
            order = Order(
                order_no='ORD-LONG-NOTE',
                customer='长备注客户',
                product_id=product.id,
                quantity=10,
                note=long_note
            )
            db.session.add(order)
            db.session.commit()
            
            # Text字段应该能存储长文本
            assert len(order.note) == 10000


@pytest.mark.boundary
class TestSpecialCharacters:
    """特殊字符测试"""
    
    def test_product_name_with_special_chars(self, test_app):
        """测试产品名称包含特殊字符"""
        with test_app.app_context():
            special_name = '产品<>&"\'\\特殊字符'
            product = Product(name=special_name)
            db.session.add(product)
            db.session.commit()
            
            assert product.name == special_name
    
    def test_product_name_with_emoji(self, test_app):
        """测试产品名称包含emoji"""
        with test_app.app_context():
            emoji_name = '产品🎉测试🎊'
            product = Product(name=emoji_name)
            db.session.add(product)
            db.session.commit()
            
            assert product.name == emoji_name
    
    def test_product_name_with_chinese(self, test_app):
        """测试产品名称包含中文"""
        with test_app.app_context():
            chinese_name = '中文产品名称测试'
            product = Product(name=chinese_name)
            db.session.add(product)
            db.session.commit()
            
            assert product.name == chinese_name
    
    def test_customer_name_with_spaces(self, test_app):
        """测试客户名称包含空格"""
        with test_app.app_context():
            product = Product(name='空格客户产品')
            db.session.add(product)
            db.session.commit()
            
            order = Order(
                order_no='ORD-SPACES',
                customer='客  户  名  称',  # 包含多个空格
                product_id=product.id,
                quantity=10
            )
            db.session.add(order)
            db.session.commit()
            
            assert order.customer == '客  户  名  称'


@pytest.mark.boundary
class TestSQLInjectionPrevention:
    """SQL注入防护测试"""
    
    def test_product_name_sql_injection(self, test_app):
        """测试产品名称SQL注入"""
        with test_app.app_context():
            # 尝试SQL注入
            injection_name = "'; DROP TABLE product; --"
            product = Product(name=injection_name)
            db.session.add(product)
            db.session.commit()
            
            # 应该安全存储,不会执行SQL
            assert product.name == injection_name
            
            # 验证表仍然存在
            products = Product.query.all()
            assert isinstance(products, list)
    
    def test_customer_name_sql_injection(self, test_app):
        """测试客户名称SQL注入"""
        with test_app.app_context():
            product = Product(name='SQL注入测试产品')
            db.session.add(product)
            db.session.commit()
            
            injection_customer = "1' OR '1'='1"
            order = Order(
                order_no='ORD-INJECTION',
                customer=injection_customer,
                product_id=product.id,
                quantity=10
            )
            db.session.add(order)
            db.session.commit()
            
            # 应该安全存储
            assert order.customer == injection_customer


@pytest.mark.boundary
class TestXSSPrevention:
    """XSS防护测试"""
    
    def test_product_name_xss(self, test_app):
        """测试产品名称XSS攻击"""
        with test_app.app_context():
            xss_name = '<script>alert("XSS")</script>'
            product = Product(name=xss_name)
            db.session.add(product)
            db.session.commit()
            
            # 应该原样存储,前端负责转义
            assert product.name == xss_name
    
    def test_order_note_xss(self, test_app):
        """测试订单备注XSS攻击"""
        with test_app.app_context():
            product = Product(name='XSS测试产品')
            db.session.add(product)
            db.session.commit()
            
            xss_note = '<img src=x onerror=alert("XSS")>'
            order = Order(
                order_no='ORD-XSS',
                customer='XSS客户',
                product_id=product.id,
                quantity=10,
                note=xss_note
            )
            db.session.add(order)
            db.session.commit()
            
            # 应该原样存储
            assert order.note == xss_note
