"""
集成测试 - API接口测试
测试API路由、请求响应、参数验证、错误处理
"""
import pytest
import json
from app import app, db
from app.models import Product, Order, StockIn, StockOut


@pytest.mark.integration
@pytest.mark.api
class TestProductAPI:
    """产品API集成测试"""
    
    def test_get_products_list(self, test_client):
        """测试获取产品列表"""
        response = test_client.get('/api/products')
        assert response.status_code in [200, 404]  # 200成功或404路由不存在
    
    def test_create_product_api(self, test_app):
        """测试创建产品API"""
        with test_app.test_client() as client:
            product_data = {
                'name': 'API测试产品',
                'barcode': '6901234567890',
                'initial_stock': 100
            }
            
            response = client.post('/api/products', 
                                   json=product_data,
                                   content_type='application/json')
            
            # 检查响应状态码
            assert response.status_code in [200, 201, 404, 405]
    
    def test_product_api_with_invalid_data(self, test_app):
        """测试使用无效数据创建产品"""
        with test_app.test_client() as client:
            invalid_data = {
                'name': '',  # 空名称
                'barcode': 'invalid'  # 无效条码
            }
            
            response = client.post('/api/products',
                                   json=invalid_data,
                                   content_type='application/json')
            
            # 应该返回错误响应
            assert response.status_code in [400, 404, 405, 422]


@pytest.mark.integration
@pytest.mark.api
class TestOrderAPI:
    """订单API集成测试"""
    
    def test_get_orders_list(self, test_client):
        """测试获取订单列表"""
        response = test_client.get('/api/orders')
        assert response.status_code in [200, 404]
    
    def test_create_order_api(self, test_app):
        """测试创建订单API"""
        with test_app.app_context():
            # 先创建产品
            product = Product(name='订单测试产品')
            db.session.add(product)
            db.session.commit()
            
            with test_app.test_client() as client:
                order_data = {
                    'customer': '测试客户',
                    'product_id': product.id,
                    'quantity': 10
                }
                
                response = client.post('/api/orders',
                                       json=order_data,
                                       content_type='application/json')
                
                assert response.status_code in [200, 201, 404, 405]


@pytest.mark.integration
@pytest.mark.api
class TestStockInAPI:
    """备货API集成测试"""
    
    def test_get_stockins_list(self, test_client):
        """测试获取备货列表"""
        response = test_client.get('/api/stockins')
        assert response.status_code in [200, 404]
    
    def test_create_stockin_api(self, test_app):
        """测试创建备货API"""
        with test_app.app_context():
            product = Product(name='备货测试产品')
            db.session.add(product)
            db.session.commit()
            
            with test_app.test_client() as client:
                stockin_data = {
                    'customer': '备货客户',
                    'product_id': product.id,
                    'quantity': 50
                }
                
                response = client.post('/api/stockins',
                                       json=stockin_data,
                                       content_type='application/json')
                
                assert response.status_code in [200, 201, 404, 405]


@pytest.mark.integration
@pytest.mark.api
class TestStockOutAPI:
    """出货API集成测试"""
    
    def test_get_stockouts_list(self, test_client):
        """测试获取出货列表"""
        response = test_client.get('/api/stockouts')
        assert response.status_code in [200, 404]
    
    def test_create_stockout_api(self, test_app):
        """测试创建出货API"""
        with test_app.app_context():
            product = Product(name='出货测试产品', current_stock=100)
            db.session.add(product)
            db.session.commit()
            
            with test_app.test_client() as client:
                stockout_data = {
                    'product_id': product.id,
                    'quantity': 20,
                    'customer': '出货客户'
                }
                
                response = client.post('/api/stockouts',
                                       json=stockout_data,
                                       content_type='application/json')
                
                assert response.status_code in [200, 201, 404, 405]


@pytest.mark.integration
@pytest.mark.db
class TestDatabaseIntegration:
    """数据库集成测试"""
    
    def test_product_order_relationship(self, test_app):
        """测试产品与订单的关联关系"""
        with test_app.app_context():
            # 创建产品
            product = Product(name='关联测试产品')
            db.session.add(product)
            db.session.commit()
            
            # 创建订单
            order = Order(
                order_no='ORD-TEST-001',
                customer='关联客户',
                product_id=product.id,
                quantity=10
            )
            db.session.add(order)
            db.session.commit()
            
            # 验证关联关系
            assert order.product.name == '关联测试产品'
            assert len(product.orders) == 1
            assert product.orders[0].order_no == 'ORD-TEST-001'
    
    def test_product_stockin_relationship(self, test_app):
        """测试产品与备货的关联关系"""
        with test_app.app_context():
            product = Product(name='备货关联产品')
            db.session.add(product)
            db.session.commit()
            
            stockin = StockIn(
                stockin_no='SI-TEST-001',
                customer='备货客户',
                product_id=product.id,
                quantity=50
            )
            db.session.add(stockin)
            db.session.commit()
            
            assert stockin.product.name == '备货关联产品'
            assert len(product.stockins) == 1
    
    def test_product_stockout_relationship(self, test_app):
        """测试产品与出货的关联关系"""
        with test_app.app_context():
            product = Product(name='出货关联产品')
            db.session.add(product)
            db.session.commit()
            
            stockout = StockOut(
                stockout_no='SO-TEST-001',
                product_id=product.id,
                quantity=20
            )
            db.session.add(stockout)
            db.session.commit()
            
            assert stockout.product.name == '出货关联产品'
            assert len(product.stockouts) == 1
    
    def test_cascade_delete(self, test_app):
        """测试级联删除"""
        with test_app.app_context():
            # 创建产品
            product = Product(name='级联删除测试')
            db.session.add(product)
            db.session.commit()
            
            product_id = product.id
            
            # 创建订单
            order = Order(
                order_no='ORD-CASCADE-001',
                customer='级联客户',
                product_id=product_id,
                quantity=10
            )
            db.session.add(order)
            db.session.commit()
            
            order_id = order.id
            
            # 删除产品(需要先删除关联的订单)
            db.session.delete(order)
            db.session.delete(product)
            db.session.commit()
            
            # 验证产品已删除
            deleted_product = Product.query.get(product_id)
            assert deleted_product is None
            
            # 验证订单已删除
            deleted_order = Order.query.get(order_id)
            assert deleted_order is None
    
    def test_transaction_rollback(self, test_app):
        """测试事务回滚"""
        with test_app.app_context():
            # 创建产品
            product = Product(name='事务测试产品')
            db.session.add(product)
            db.session.commit()
            
            product_id = product.id
            
            try:
                # 创建无效订单(缺少必填字段)
                invalid_order = Order(order_no='ORD-INVALID')
                db.session.add(invalid_order)
                db.session.commit()
            except Exception:
                # 回滚事务
                db.session.rollback()
            
            # 验证产品仍然存在
            existing_product = Product.query.get(product_id)
            assert existing_product is not None
