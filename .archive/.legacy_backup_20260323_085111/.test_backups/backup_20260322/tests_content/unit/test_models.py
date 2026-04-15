"""
数据模型单元测试
测试Product、Order、StockIn、StockOut、User等核心模型
"""
import pytest
from datetime import datetime
from app import db
from app.models import Product, Order, StockIn, StockOut, User, Permission, Case
from werkzeug.security import generate_password_hash, check_password_hash


@pytest.mark.unit
@pytest.mark.model
class TestProductModel:
    """Product模型测试"""
    
    def test_create_product(self, test_app):
        """测试创建产品"""
        with test_app.app_context():
            product = Product(
                name='测试产品',
                barcode='6901234567890',
                initial_stock=100,
                current_stock=100
            )
            db.session.add(product)
            db.session.commit()
            
            assert product.id is not None
            assert product.name == '测试产品'
            assert product.barcode == '6901234567890'
            assert product.initial_stock == 100
            assert product.current_stock == 100
    
    def test_product_repr(self, test_app):
        """测试产品字符串表示"""
        product = Product(name='测试产品')
        assert repr(product) == '<Product 测试产品>'
    
    def test_product_default_values(self, test_app):
        """测试产品默认值"""
        with test_app.app_context():
            product = Product(name='默认产品')
            db.session.add(product)
            db.session.commit()
            
            assert product.initial_stock == 0
            assert product.current_stock == 0
            assert product.create_time is not None
    
    def test_product_query_by_name(self, test_app):
        """测试按名称查询产品"""
        with test_app.app_context():
            product = Product(name='查询测试产品', barcode='6901111111111')
            db.session.add(product)
            db.session.commit()
            
            found = Product.query.filter_by(name='查询测试产品').first()
            assert found is not None
            assert found.barcode == '6901111111111'
    
    def test_product_update_stock(self, test_app):
        """测试更新产品库存"""
        with test_app.app_context():
            product = Product(name='库存测试', current_stock=100)
            db.session.add(product)
            db.session.commit()
            
            product.current_stock = 150
            db.session.commit()
            
            updated = Product.query.get(product.id)
            assert updated.current_stock == 150


@pytest.mark.unit
@pytest.mark.model
class TestOrderModel:
    """Order模型测试"""
    
    def test_create_order(self, test_app):
        """测试创建订单"""
        with test_app.app_context():
            # 先创建产品
            product = Product(name='订单产品')
            db.session.add(product)
            db.session.commit()
            
            # 创建订单
            order = Order(
                order_no='ORD20260321001',
                customer='测试客户',
                product_id=product.id,
                quantity=10,
                status='待备货'
            )
            db.session.add(order)
            db.session.commit()
            
            assert order.id is not None
            assert order.order_no == 'ORD20260321001'
            assert order.customer == '测试客户'
            assert order.status == '待备货'
    
    def test_order_product_relationship(self, test_app):
        """测试订单与产品的关联关系"""
        with test_app.app_context():
            product = Product(name='关联产品')
            db.session.add(product)
            db.session.commit()
            
            order = Order(
                order_no='ORD20260321002',
                customer='关联客户',
                product_id=product.id,
                quantity=5
            )
            db.session.add(order)
            db.session.commit()
            
            # 测试关联关系
            assert order.product.name == '关联产品'
            assert len(product.orders) == 1
    
    def test_order_default_status(self, test_app):
        """测试订单默认状态"""
        with test_app.app_context():
            product = Product(name='状态产品')
            db.session.add(product)
            db.session.commit()
            
            order = Order(
                order_no='ORD20260321003',
                customer='状态客户',
                product_id=product.id,
                quantity=1
            )
            db.session.add(order)
            db.session.commit()
            
            assert order.status == '待备货'
    
    def test_order_repr(self, test_app):
        """测试订单字符串表示"""
        order = Order(order_no='ORD20260321004')
        assert repr(order) == '<Order ORD20260321004>'


@pytest.mark.unit
@pytest.mark.model
class TestStockInModel:
    """StockIn模型测试"""
    
    def test_create_stockin(self, test_app):
        """测试创建备货记录"""
        with test_app.app_context():
            product = Product(name='备货产品')
            db.session.add(product)
            db.session.commit()
            
            stockin = StockIn(
                stockin_no='SI20260321001',
                customer='备货客户',
                product_id=product.id,
                quantity=50
            )
            db.session.add(stockin)
            db.session.commit()
            
            assert stockin.id is not None
            assert stockin.stockin_no == 'SI20260321001'
            assert stockin.quantity == 50
    
    def test_stockin_product_relationship(self, test_app):
        """测试备货与产品的关联"""
        with test_app.app_context():
            product = Product(name='备货关联产品')
            db.session.add(product)
            db.session.commit()
            
            stockin = StockIn(
                stockin_no='SI20260321002',
                customer='关联客户',
                product_id=product.id,
                quantity=30
            )
            db.session.add(stockin)
            db.session.commit()
            
            assert stockin.product.name == '备货关联产品'
            assert len(product.stockins) == 1


@pytest.mark.unit
@pytest.mark.model
class TestStockOutModel:
    """StockOut模型测试"""
    
    def test_create_stockout(self, test_app):
        """测试创建出货记录"""
        with test_app.app_context():
            product = Product(name='出货产品')
            db.session.add(product)
            db.session.commit()
            
            stockout = StockOut(
                stockout_no='SO20260321001',
                product_id=product.id,
                quantity=20,
                customer='出货客户'
            )
            db.session.add(stockout)
            db.session.commit()
            
            assert stockout.id is not None
            assert stockout.stockout_no == 'SO20260321001'
            assert stockout.quantity == 20
    
    def test_stockout_relationships(self, test_app):
        """测试出货的多重关联关系"""
        with test_app.app_context():
            product = Product(name='多重关联产品')
            db.session.add(product)
            db.session.commit()
            
            order = Order(
                order_no='ORD20260321005',
                customer='订单客户',
                product_id=product.id,
                quantity=10
            )
            db.session.add(order)
            db.session.commit()
            
            stockin = StockIn(
                stockin_no='SI20260321003',
                customer='备货客户',
                product_id=product.id,
                quantity=10
            )
            db.session.add(stockin)
            db.session.commit()
            
            stockout = StockOut(
                stockout_no='SO20260321002',
                product_id=product.id,
                quantity=10,
                order_id=order.id,
                stockin_id=stockin.id
            )
            db.session.add(stockout)
            db.session.commit()
            
            assert stockout.product.name == '多重关联产品'
            assert stockout.order.order_no == 'ORD20260321005'
            assert stockout.stockin.stockin_no == 'SI20260321003'


@pytest.mark.unit
@pytest.mark.model
class TestUserModel:
    """User模型测试"""
    
    def test_create_user(self, test_app):
        """测试创建用户"""
        with test_app.app_context():
            user = User(
                username='testuser',
                password=generate_password_hash('password123'),
                is_super=False,
                status=True
            )
            db.session.add(user)
            db.session.commit()
            
            assert user.id is not None
            assert user.username == 'testuser'
            assert user.is_super is False
            assert user.status is True
    
    def test_user_password_hash(self, test_app):
        """测试用户密码哈希"""
        with test_app.app_context():
            user = User(
                username='hashtest',
                password=generate_password_hash('mypassword')
            )
            db.session.add(user)
            db.session.commit()
            
            # 验证密码
            assert check_password_hash(user.password, 'mypassword')
            assert not check_password_hash(user.password, 'wrongpassword')
    
    def test_user_unique_username(self, test_app):
        """测试用户名唯一性"""
        with test_app.app_context():
            user1 = User(username='uniqueuser', password='pass1')
            db.session.add(user1)
            db.session.commit()
            
            # 尝试创建同名用户应该失败
            user2 = User(username='uniqueuser', password='pass2')
            db.session.add(user2)
            
            with pytest.raises(Exception):
                db.session.commit()
    
    def test_user_has_permission(self, test_app):
        """测试用户权限检查"""
        with test_app.app_context():
            # 创建权限
            perm = Permission(name='测试权限', code='test_perm')
            db.session.add(perm)
            db.session.commit()
            
            # 创建用户并关联权限
            user = User(username='permuser', password='pass')
            user.permissions.append(perm)
            db.session.add(user)
            db.session.commit()
            
            assert user.has_permission('test_perm') is True
            assert user.has_permission('other_perm') is False
    
    def test_superuser_has_all_permissions(self, test_app):
        """测试超级用户拥有所有权限"""
        with test_app.app_context():
            superuser = User(
                username='superuser',
                password='pass',
                is_super=True
            )
            db.session.add(superuser)
            db.session.commit()
            
            assert superuser.has_permission('any_permission') is True


@pytest.mark.unit
@pytest.mark.model
class TestCaseModel:
    """Case模型测试"""
    
    def test_create_case(self, test_app):
        """测试创建皮套"""
        with test_app.app_context():
            case = Case(
                name='测试皮套',
                barcode='6909999999999',
                initial_stock=50,
                current_stock=50
            )
            db.session.add(case)
            db.session.commit()
            
            assert case.id is not None
            assert case.name == '测试皮套'
            assert case.current_stock == 50
    
    def test_case_repr(self, test_app):
        """测试皮套字符串表示"""
        case = Case(name='皮套测试')
        assert repr(case) == '<Case 皮套测试>'
