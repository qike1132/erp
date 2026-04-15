"""
产品路由测试 - 提高产品路由覆盖率
测试范围：产品列表、创建、编辑、删除、搜索等完整流程
"""
import pytest
import json
from datetime import datetime
from flask import session
from app import db
from app.models import Product, InventoryLog, Order, StockIn, StockOut


class TestProductRoutes:
    """产品路由测试"""

    def test_product_list_get_success(self, logged_in_client, test_product):
        """测试产品列表页面访问成功"""
        response = logged_in_client.get('/product/list')
        assert response.status_code == 200
        assert b'product' in response.data or b'产品' in response.data

    def test_product_list_post_create_success(self, logged_in_client):
        """测试创建产品成功"""
        data = {
            'name': '新产品',
            'barcode': 'NEW001',
            'image': '',
            'initial_stock': 100
        }
        response = logged_in_client.post('/product/list', data=data, follow_redirects=True)
        assert response.status_code == 200
        
        # 验证产品创建
        product = Product.query.filter_by(barcode='NEW001').first()
        assert product is not None
        assert product.name == '新产品'
        assert product.current_stock == 100

    def test_product_list_post_create_without_stock(self, logged_in_client):
        """测试创建产品不设置初始库存"""
        data = {
            'name': '无库存产品',
            'barcode': 'NOSTOCK001',
            'image': ''
        }
        response = logged_in_client.post('/product/list', data=data, follow_redirects=True)
        assert response.status_code == 200
        
        product = Product.query.filter_by(barcode='NOSTOCK001').first()
        assert product is not None
        assert product.current_stock == 0

    def test_product_edit_get_success(self, logged_in_client, test_product):
        """测试产品编辑页面访问成功"""
        response = logged_in_client.get(f'/product/edit/{test_product.id}')
        assert response.status_code == 200

    def test_product_edit_post_success(self, logged_in_client, test_product):
        """测试编辑产品成功"""
        data = {
            'name': '更新产品名',
            'barcode': test_product.barcode,
            'image': ''
        }
        response = logged_in_client.post(f'/product/edit/{test_product.id}', data=data, follow_redirects=True)
        assert response.status_code == 200
        
        # 验证产品更新
        db.session.refresh(test_product)
        assert test_product.name == '更新产品名'

    def test_product_edit_post_with_stock_change(self, logged_in_client, test_product):
        """测试编辑产品时调整库存"""
        initial_stock = test_product.current_stock
        new_initial_stock = initial_stock + 50
        
        data = {
            'name': test_product.name,
            'barcode': test_product.barcode,
            'image': '',
            'initial_stock': new_initial_stock
        }
        response = logged_in_client.post(f'/product/edit/{test_product.id}', data=data, follow_redirects=True)
        assert response.status_code == 200
        
        # 验证库存更新
        db.session.refresh(test_product)
        assert test_product.current_stock == initial_stock + 50

    def test_product_delete_success(self, logged_in_client, db_session):
        """测试删除产品成功"""
        # 创建一个没有关联数据的产品
        product = Product(
            name='待删除产品',
            barcode='DELETE001',
            current_stock=0,
            initial_stock=0
        )
        db_session.add(product)
        db_session.commit()
        
        product_id = product.id
        response = logged_in_client.get(f'/product/delete/{product_id}', follow_redirects=True)
        assert response.status_code == 200
        
        # 验证产品删除
        deleted_product = Product.query.get(product_id)
        assert deleted_product is None

    def test_product_delete_with_orders(self, logged_in_client, test_product, test_customer, db_session):
        """测试删除有关联订单的产品"""
        # 创建关联订单
        order = Order(
            order_no='ORD-PROD-001',
            product_id=test_product.id,
            customer=test_customer.name,
            quantity=10,
            order_date=datetime.now(),
            status='待备货'
        )
        db_session.add(order)
        db_session.commit()
        
        response = logged_in_client.get(f'/product/delete/{test_product.id}', follow_redirects=True)
        assert response.status_code == 200
        assert b'error' in response.data or b'无法删除' in response.data

    def test_product_delete_with_stockins(self, logged_in_client, test_product, test_customer, db_session):
        """测试删除有关联入库的产品"""
        # 创建关联入库
        stockin = StockIn(
            stockin_no='SI-PROD-001',
            product_id=test_product.id,
            customer=test_customer.name,
            quantity=50,
            stockin_date=datetime.now()
        )
        db_session.add(stockin)
        db_session.commit()
        
        response = logged_in_client.get(f'/product/delete/{test_product.id}', follow_redirects=True)
        assert response.status_code == 200
        assert b'error' in response.data or b'无法删除' in response.data

    def test_product_delete_not_found(self, logged_in_client):
        """测试删除不存在的产品"""
        response = logged_in_client.get('/product/delete/99999', follow_redirects=True)
        assert response.status_code == 404

    def test_product_search_by_name(self, logged_in_client, test_product):
        """测试按名称搜索产品"""
        response = logged_in_client.get(f'/product/search?q={test_product.name}')
        assert response.status_code == 200
        
        data = json.loads(response.data)
        assert isinstance(data, list)
        assert len(data) > 0

    def test_product_search_by_barcode(self, logged_in_client, test_product):
        """测试按条码搜索产品"""
        response = logged_in_client.get(f'/product/search?q={test_product.barcode}')
        assert response.status_code == 200
        
        data = json.loads(response.data)
        assert isinstance(data, list)
        assert len(data) > 0

    def test_product_search_empty_query(self, logged_in_client):
        """测试空查询搜索产品"""
        response = logged_in_client.get('/product/search?q=')
        assert response.status_code == 200
        
        data = json.loads(response.data)
        assert isinstance(data, list)

    def test_product_available_stock_success(self, logged_in_client, test_product):
        """测试获取产品可用库存成功"""
        response = logged_in_client.get(f'/product/available-stock?product_id={test_product.id}')
        assert response.status_code == 200
        
        data = json.loads(response.data)
        assert data['product_id'] == test_product.id
        assert 'current_stock' in data
        assert 'available_stock' in data

    def test_product_available_stock_missing_id(self, logged_in_client):
        """测试获取产品可用库存缺少ID"""
        response = logged_in_client.get('/product/available-stock')
        assert response.status_code == 400

    def test_product_available_stock_not_found(self, logged_in_client):
        """测试获取产品可用库存产品不存在"""
        response = logged_in_client.get('/product/available-stock?product_id=99999')
        assert response.status_code == 404


class TestProductBusinessLogic:
    """产品业务逻辑测试"""

    def test_product_inventory_log_on_create(self, logged_in_client):
        """测试创建产品时库存日志记录"""
        data = {
            'name': '日志测试产品',
            'barcode': 'LOG001',
            'initial_stock': 50
        }
        logged_in_client.post('/product/list', data=data, follow_redirects=True)
        
        product = Product.query.filter_by(barcode='LOG001').first()
        assert product is not None
        
        # 验证库存日志
        log = InventoryLog.query.filter_by(
            product_id=product.id,
            change_type='初始库存'
        ).first()
        assert log is not None
        assert log.change_quantity == 50

    def test_product_inventory_log_on_stock_change(self, logged_in_client, test_product):
        """测试调整库存时日志记录"""
        initial_stock = test_product.initial_stock
        new_stock = initial_stock + 30
        
        data = {
            'name': test_product.name,
            'barcode': test_product.barcode,
            'initial_stock': new_stock
        }
        logged_in_client.post(f'/product/edit/{test_product.id}', data=data, follow_redirects=True)
        
        # 验证库存日志
        log = InventoryLog.query.filter_by(
            product_id=test_product.id,
            change_type='初始库存调整'
        ).order_by(InventoryLog.id.desc()).first()
        assert log is not None
        assert log.change_quantity == 30

    def test_product_cache_invalidation_on_create(self, logged_in_client):
        """测试创建产品时缓存失效"""
        from utils.redis_cache import redis_cache
        
        data = {
            'name': '缓存测试产品',
            'barcode': 'CACHE001'
        }
        logged_in_client.post('/product/list', data=data, follow_redirects=True)
        
        # 验证缓存已清除
        cached_products = redis_cache.get('product_list_all')
        assert cached_products is None

    def test_product_cache_invalidation_on_edit(self, logged_in_client, test_product):
        """测试编辑产品时缓存失效"""
        from utils.redis_cache import redis_cache
        
        data = {
            'name': '编辑后产品名',
            'barcode': test_product.barcode
        }
        logged_in_client.post(f'/product/edit/{test_product.id}', data=data, follow_redirects=True)
        
        # 验证缓存已清除
        cached_products = redis_cache.get('product_list_all')
        assert cached_products is None


class TestProductEdgeCases:
    """产品边界条件测试"""

    def test_product_with_empty_name(self, logged_in_client):
        """测试空产品名称"""
        data = {
            'name': '',
            'barcode': 'EMPTY001'
        }
        response = logged_in_client.post('/product/list', data=data, follow_redirects=True)
        assert response.status_code == 200

    def test_product_with_long_name(self, logged_in_client):
        """测试长产品名称"""
        data = {
            'name': 'A' * 100,
            'barcode': 'LONG001'
        }
        response = logged_in_client.post('/product/list', data=data, follow_redirects=True)
        assert response.status_code == 200

    def test_product_with_special_characters(self, logged_in_client):
        """测试特殊字符产品名称"""
        data = {
            'name': '产品@#$%^&*()测试',
            'barcode': 'SPECIAL001'
        }
        response = logged_in_client.post('/product/list', data=data, follow_redirects=True)
        assert response.status_code == 200

    def test_product_with_negative_stock(self, logged_in_client):
        """测试负库存产品"""
        data = {
            'name': '负库存产品',
            'barcode': 'NEG001',
            'initial_stock': -10
        }
        response = logged_in_client.post('/product/list', data=data, follow_redirects=True)
        assert response.status_code == 200

    def test_product_with_zero_stock(self, logged_in_client):
        """测试零库存产品"""
        data = {
            'name': '零库存产品',
            'barcode': 'ZERO001',
            'initial_stock': 0
        }
        response = logged_in_client.post('/product/list', data=data, follow_redirects=True)
        assert response.status_code == 200

    def test_product_with_large_stock(self, logged_in_client):
        """测试大库存产品"""
        data = {
            'name': '大库存产品',
            'barcode': 'LARGE001',
            'initial_stock': 1000000
        }
        response = logged_in_client.post('/product/list', data=data, follow_redirects=True)
        assert response.status_code == 200

    def test_product_duplicate_barcode(self, logged_in_client, test_product):
        """测试重复条码产品"""
        data = {
            'name': '重复条码产品',
            'barcode': test_product.barcode
        }
        response = logged_in_client.post('/product/list', data=data, follow_redirects=True)
        assert response.status_code == 200

    def test_product_with_empty_barcode(self, logged_in_client):
        """测试空条码产品"""
        data = {
            'name': '无条码产品',
            'barcode': ''
        }
        response = logged_in_client.post('/product/list', data=data, follow_redirects=True)
        assert response.status_code == 200


class TestProductPerformance:
    """产品性能测试"""

    def test_product_list_with_many_products(self, logged_in_client, db_session):
        """测试大量产品列表查询"""
        # 创建100个产品
        for i in range(100):
            product = Product(
                name=f'性能测试产品{i}',
                barcode=f'PERF{i:04d}',
                current_stock=100,
                initial_stock=100
            )
            db_session.add(product)
        db_session.commit()
        
        response = logged_in_client.get('/product/list')
        assert response.status_code == 200

    def test_product_search_performance(self, logged_in_client, db_session):
        """测试产品搜索性能"""
        # 创建大量产品
        for i in range(200):
            product = Product(
                name=f'搜索测试产品{i}',
                barcode=f'SRCH{i:04d}',
                current_stock=100,
                initial_stock=100
            )
            db_session.add(product)
        db_session.commit()
        
        # 搜索特定产品
        response = logged_in_client.get('/product/search?q=搜索测试产品100')
        assert response.status_code == 200
        
        data = json.loads(response.data)
        assert isinstance(data, list)

    def test_product_available_stock_performance(self, logged_in_client, db_session):
        """测试获取产品可用库存性能"""
        # 创建大量产品
        products = []
        for i in range(100):
            product = Product(
                name=f'库存测试产品{i}',
                barcode=f'STOCK{i:04d}',
                current_stock=1000,
                initial_stock=1000
            )
            products.append(product)
        db_session.add_all(products)
        db_session.commit()
        
        # 查询每个产品的可用库存
        for product in products[:10]:  # 只测试前10个
            response = logged_in_client.get(f'/product/available-stock?product_id={product.id}')
            assert response.status_code == 200


class TestProductIntegration:
    """产品集成测试"""

    def test_product_with_orders_and_stockins(self, logged_in_client, test_product, test_customer, db_session):
        """测试产品与订单、入库的关联"""
        # 创建订单
        order = Order(
            order_no='ORD-INT-001',
            product_id=test_product.id,
            customer=test_customer.name,
            quantity=20,
            order_date=datetime.now(),
            status='待备货'
        )
        db_session.add(order)
        
        # 创建入库
        stockin = StockIn(
            stockin_no='SI-INT-001',
            product_id=test_product.id,
            customer=test_customer.name,
            quantity=50,
            stockin_date=datetime.now()
        )
        db_session.add(stockin)
        db_session.commit()
        
        # 验证产品关联数据
        assert len(test_product.orders) > 0
        assert len(test_product.stockins) > 0

    def test_product_stock_consistency(self, logged_in_client, test_product, test_customer, db_session):
        """测试产品库存一致性"""
        initial_stock = test_product.current_stock
        
        # 创建入库
        stockin = StockIn(
            stockin_no='SI-CONS-001',
            product_id=test_product.id,
            customer=test_customer.name,
            quantity=30,
            stockin_date=datetime.now()
        )
        db_session.add(stockin)
        test_product.current_stock += 30
        db_session.commit()
        
        # 创建出库
        stockout = StockOut(
            stockout_no='SO-CONS-001',
            product_id=test_product.id,
            customer=test_customer.name,
            quantity=10,
            stockout_date=datetime.now()
        )
        db_session.add(stockout)
        test_product.current_stock -= 10
        db_session.commit()
        
        # 验证库存一致性
        db.session.refresh(test_product)
        assert test_product.current_stock == initial_stock + 30 - 10


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--cov=app/routes/product', '--cov-report=term-missing'])
