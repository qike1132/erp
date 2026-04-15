"""
库存路由测试 - 提高库存路由覆盖率
测试范围：入库、出库、库存查看等完整流程
"""
import pytest
import json
from datetime import datetime
from flask import session
from app import db
from app.models import Product, StockIn, StockOut, InventoryLog, Customer


class TestStockInRoutes:
    """入库路由测试"""

    def test_stockin_list_get_success(self, logged_in_client, test_stockin):
        """测试入库列表页面访问成功"""
        response = logged_in_client.get('/stock/in/list')
        assert response.status_code == 200
        assert b'stockin' in response.data or b'入库' in response.data

    def test_stockin_list_post_create_success(self, logged_in_client, test_product, test_customer):
        """测试创建入库记录成功"""
        initial_stock = test_product.current_stock
        data = {
            'product_id': test_product.id,
            'customer': test_customer.name,
            'quantity': 50,
            'stockin_date': datetime.now().strftime('%Y-%m-%d'),
            'note': '测试入库'
        }
        response = logged_in_client.post('/stock/in/list', data=data, follow_redirects=True)
        assert response.status_code == 200
        
        # 验证库存增加
        db.session.refresh(test_product)
        assert test_product.current_stock == initial_stock + 50

    def test_stockin_list_post_missing_product(self, logged_in_client, test_customer):
        """测试创建入库记录缺少产品ID"""
        data = {
            'customer': test_customer.name,
            'quantity': 50,
            'stockin_date': datetime.now().strftime('%Y-%m-%d')
        }
        response = logged_in_client.post('/stock/in/list', data=data, follow_redirects=True)
        assert response.status_code in [200, 400]

    def test_stockin_list_post_nonexistent_product(self, logged_in_client, test_customer):
        """测试创建入库记录产品不存在"""
        data = {
            'product_id': 99999,
            'customer': test_customer.name,
            'quantity': 50,
            'stockin_date': datetime.now().strftime('%Y-%m-%d')
        }
        response = logged_in_client.post('/stock/in/list', data=data, follow_redirects=True)
        assert response.status_code == 200

    def test_stockin_edit_get_success(self, logged_in_client, test_stockin):
        """测试入库编辑页面访问成功"""
        response = logged_in_client.get(f'/stock/in/edit/{test_stockin.id}')
        assert response.status_code == 200

    def test_stockin_edit_post_success(self, logged_in_client, test_stockin, test_product, test_customer):
        """测试编辑入库记录成功"""
        old_quantity = test_stockin.quantity
        new_quantity = old_quantity + 20
        
        data = {
            'customer': test_customer.name,
            'quantity': new_quantity,
            'stockin_date': datetime.now().strftime('%Y-%m-%d'),
            'note': '更新后的入库'
        }
        response = logged_in_client.post(f'/stock/in/edit/{test_stockin.id}', data=data, follow_redirects=True)
        assert response.status_code == 200
        
        # 验证入库记录更新
        db.session.refresh(test_stockin)
        assert test_stockin.quantity == new_quantity

    def test_stockin_edit_post_stock_update(self, logged_in_client, test_stockin, test_product, test_customer):
        """测试编辑入库记录时库存更新"""
        initial_stock = test_product.current_stock
        old_quantity = test_stockin.quantity
        new_quantity = old_quantity + 30
        
        data = {
            'customer': test_customer.name,
            'quantity': new_quantity,
            'stockin_date': datetime.now().strftime('%Y-%m-%d'),
            'note': '更新'
        }
        logged_in_client.post(f'/stock/in/edit/{test_stockin.id}', data=data, follow_redirects=True)
        
        db.session.refresh(test_product)
        assert test_product.current_stock == initial_stock + 30

    def test_stockin_delete_success(self, logged_in_client, test_stockin, test_product):
        """测试删除入库记录成功"""
        initial_stock = test_product.current_stock
        stockin_id = test_stockin.id
        stockin_quantity = test_stockin.quantity
        
        response = logged_in_client.get(f'/stock/in/delete/{stockin_id}', follow_redirects=True)
        assert response.status_code == 200
        
        # 验证入库记录删除
        deleted_stockin = StockIn.query.get(stockin_id)
        assert deleted_stockin is None
        
        # 验证库存减少
        db.session.refresh(test_product)
        assert test_product.current_stock == initial_stock - stockin_quantity

    def test_stockin_delete_not_found(self, logged_in_client):
        """测试删除不存在的入库记录"""
        response = logged_in_client.get('/stock/in/delete/99999', follow_redirects=True)
        assert response.status_code == 404

    def test_stockin_delete_with_stockouts(self, logged_in_client, test_stockin, test_product, test_customer, db_session):
        """测试删除有关联出库的入库记录"""
        # 创建关联的出库记录
        stockout = StockOut(
            stockout_no='SO-TEST-001',
            product_id=test_product.id,
            customer=test_customer.name,
            quantity=10,
            stockin_id=test_stockin.id,
            stockout_date=datetime.now()
        )
        db_session.add(stockout)
        db_session.commit()
        
        # 尝试删除入库记录
        response = logged_in_client.get(f'/stock/in/delete/{test_stockin.id}', follow_redirects=True)
        assert response.status_code == 200
        # 应该提示无法删除
        assert b'error' in response.data or b'无法删除' in response.data


class TestStockOutRoutes:
    """出库路由测试"""

    def test_stockout_list_get_success(self, logged_in_client):
        """测试出库列表页面访问成功"""
        response = logged_in_client.get('/stock/out/list')
        assert response.status_code == 200
        assert b'stockout' in response.data or b'出库' in response.data

    def test_stockout_list_post_create_success(self, logged_in_client, test_product):
        """测试创建出库记录成功"""
        test_product.current_stock = 100
        db.session.commit()
        
        initial_stock = test_product.current_stock
        data = {
            'product_id': test_product.id,
            'quantity': 20,
            'stockout_date': datetime.now().strftime('%Y-%m-%d'),
            'note': '测试出库'
        }
        response = logged_in_client.post('/stock/out/list', data=data, follow_redirects=True)
        assert response.status_code == 200
        
        # 验证库存减少
        db.session.refresh(test_product)
        assert test_product.current_stock == initial_stock - 20

    def test_stockout_list_post_insufficient_stock(self, logged_in_client, test_product):
        """测试库存不足时出库"""
        test_product.current_stock = 10
        db.session.commit()
        
        data = {
            'product_id': test_product.id,
            'quantity': 100,
            'stockout_date': datetime.now().strftime('%Y-%m-%d')
        }
        response = logged_in_client.post('/stock/out/list', data=data, follow_redirects=True)
        assert response.status_code == 200
        assert b'error' in response.data or b'库存不足' in response.data

    def test_stockout_list_post_nonexistent_product(self, logged_in_client):
        """测试创建出库记录产品不存在"""
        data = {
            'product_id': 99999,
            'quantity': 20,
            'stockout_date': datetime.now().strftime('%Y-%m-%d')
        }
        response = logged_in_client.post('/stock/out/list', data=data, follow_redirects=True)
        assert response.status_code == 200

    def test_stockout_edit_get_success(self, logged_in_client, test_stockout):
        """测试出库编辑页面访问成功"""
        response = logged_in_client.get(f'/stock/out/edit/{test_stockout.id}')
        assert response.status_code == 200

    def test_stockout_edit_post_success(self, logged_in_client, test_stockout, test_product):
        """测试编辑出库记录成功"""
        test_product.current_stock = 100
        db.session.commit()
        
        old_quantity = test_stockout.quantity
        new_quantity = old_quantity + 5
        
        data = {
            'quantity': new_quantity,
            'stockout_date': datetime.now().strftime('%Y-%m-%d'),
            'note': '更新后的出库'
        }
        response = logged_in_client.post(f'/stock/out/edit/{test_stockout.id}', data=data, follow_redirects=True)
        assert response.status_code == 200
        
        # 验证出库记录更新
        db.session.refresh(test_stockout)
        assert test_stockout.quantity == new_quantity

    def test_stockout_edit_post_insufficient_stock(self, logged_in_client, test_stockout, test_product):
        """测试编辑出库记录库存不足"""
        test_product.current_stock = 5
        db.session.commit()
        
        data = {
            'quantity': 100,
            'stockout_date': datetime.now().strftime('%Y-%m-%d')
        }
        response = logged_in_client.post(f'/stock/out/edit/{test_stockout.id}', data=data, follow_redirects=True)
        assert response.status_code == 200

    def test_stockout_delete_success(self, logged_in_client, test_stockout, test_product):
        """测试删除出库记录成功"""
        initial_stock = test_product.current_stock
        stockout_id = test_stockout.id
        stockout_quantity = test_stockout.quantity
        
        response = logged_in_client.get(f'/stock/out/delete/{stockout_id}', follow_redirects=True)
        assert response.status_code == 200
        
        # 验证出库记录删除
        deleted_stockout = StockOut.query.get(stockout_id)
        assert deleted_stockout is None
        
        # 验证库存恢复
        db.session.refresh(test_product)
        assert test_product.current_stock == initial_stock + stockout_quantity

    def test_stockout_delete_not_found(self, logged_in_client):
        """测试删除不存在的出库记录"""
        response = logged_in_client.get('/stock/out/delete/99999', follow_redirects=True)
        assert response.status_code == 404


class TestInventoryRoutes:
    """库存查看路由测试"""

    def test_inventory_view_success(self, logged_in_client):
        """测试库存查看页面访问成功"""
        response = logged_in_client.get('/stock/inventory')
        assert response.status_code == 200
        assert b'inventory' in response.data or b'库存' in response.data

    def test_inventory_with_products(self, logged_in_client, test_product, test_customer, db_session):
        """测试有产品时的库存查看"""
        # 创建订单
        from app.models import Order
        order = Order(
            order_no='ORD-INV-001',
            product_id=test_product.id,
            customer=test_customer.name,
            quantity=20,
            order_date=datetime.now(),
            status='待备货'
        )
        db_session.add(order)
        
        # 创建入库
        stockin = StockIn(
            stockin_no='SI-INV-001',
            product_id=test_product.id,
            customer=test_customer.name,
            quantity=50,
            stockin_date=datetime.now()
        )
        db_session.add(stockin)
        db_session.commit()
        
        response = logged_in_client.get('/stock/inventory')
        assert response.status_code == 200


class TestStockBusinessLogic:
    """库存业务逻辑测试"""

    def test_stockin_inventory_log_created(self, logged_in_client, test_product, test_customer):
        """测试入库时库存日志创建"""
        data = {
            'product_id': test_product.id,
            'customer': test_customer.name,
            'quantity': 30,
            'stockin_date': datetime.now().strftime('%Y-%m-%d')
        }
        logged_in_client.post('/stock/in/list', data=data, follow_redirects=True)
        
        # 验证库存日志
        log = InventoryLog.query.filter_by(
            product_id=test_product.id,
            change_type='入库'
        ).order_by(InventoryLog.id.desc()).first()
        assert log is not None
        assert log.change_quantity == 30

    def test_stockout_inventory_log_created(self, logged_in_client, test_product):
        """测试出库时库存日志创建"""
        test_product.current_stock = 100
        db.session.commit()
        
        data = {
            'product_id': test_product.id,
            'quantity': 25,
            'stockout_date': datetime.now().strftime('%Y-%m-%d')
        }
        logged_in_client.post('/stock/out/list', data=data, follow_redirects=True)
        
        # 验证库存日志
        log = InventoryLog.query.filter_by(
            product_id=test_product.id,
            change_type='出库'
        ).order_by(InventoryLog.id.desc()).first()
        assert log is not None
        assert log.change_quantity == -25

    def test_stockin_edit_inventory_log(self, logged_in_client, test_stockin, test_product, test_customer):
        """测试编辑入库时库存日志更新"""
        old_quantity = test_stockin.quantity
        new_quantity = old_quantity + 15
        
        data = {
            'customer': test_customer.name,
            'quantity': new_quantity,
            'stockin_date': datetime.now().strftime('%Y-%m-%d')
        }
        logged_in_client.post(f'/stock/in/edit/{test_stockin.id}', data=data, follow_redirects=True)
        
        # 验证库存日志
        log = InventoryLog.query.filter_by(
            product_id=test_product.id,
            change_type='入库修改'
        ).order_by(InventoryLog.id.desc()).first()
        assert log is not None
        assert log.change_quantity == 15


class TestStockEdgeCases:
    """库存边界条件测试"""

    def test_stockin_zero_quantity(self, logged_in_client, test_product, test_customer):
        """测试零数量入库"""
        data = {
            'product_id': test_product.id,
            'customer': test_customer.name,
            'quantity': 0,
            'stockin_date': datetime.now().strftime('%Y-%m-%d')
        }
        response = logged_in_client.post('/stock/in/list', data=data, follow_redirects=True)
        assert response.status_code == 200

    def test_stockout_zero_quantity(self, logged_in_client, test_product):
        """测试零数量出库"""
        data = {
            'product_id': test_product.id,
            'quantity': 0,
            'stockout_date': datetime.now().strftime('%Y-%m-%d')
        }
        response = logged_in_client.post('/stock/out/list', data=data, follow_redirects=True)
        assert response.status_code == 200

    def test_stockout_exact_stock(self, logged_in_client, test_product):
        """测试出库数量等于库存"""
        test_product.current_stock = 50
        db.session.commit()
        
        data = {
            'product_id': test_product.id,
            'quantity': 50,
            'stockout_date': datetime.now().strftime('%Y-%m-%d')
        }
        response = logged_in_client.post('/stock/out/list', data=data, follow_redirects=True)
        assert response.status_code == 200
        
        db.session.refresh(test_product)
        assert test_product.current_stock == 0

    def test_stockin_with_future_date(self, logged_in_client, test_product, test_customer):
        """测试未来日期入库"""
        future_date = datetime(2030, 12, 31)
        data = {
            'product_id': test_product.id,
            'customer': test_customer.name,
            'quantity': 10,
            'stockin_date': future_date.strftime('%Y-%m-%d')
        }
        response = logged_in_client.post('/stock/in/list', data=data, follow_redirects=True)
        assert response.status_code == 200

    def test_stockin_with_past_date(self, logged_in_client, test_product, test_customer):
        """测试过去日期入库"""
        past_date = datetime(2020, 1, 1)
        data = {
            'product_id': test_product.id,
            'customer': test_customer.name,
            'quantity': 10,
            'stockin_date': past_date.strftime('%Y-%m-%d')
        }
        response = logged_in_client.post('/stock/in/list', data=data, follow_redirects=True)
        assert response.status_code == 200


class TestStockPerformance:
    """库存性能测试"""

    def test_stockin_list_with_many_records(self, logged_in_client, test_product, test_customer, db_session):
        """测试大量入库记录列表查询"""
        # 创建100个入库记录
        for i in range(100):
            stockin = StockIn(
                stockin_no=f'SI-PERF-{i:04d}',
                product_id=test_product.id,
                customer=test_customer.name,
                quantity=10,
                stockin_date=datetime.now()
            )
            db_session.add(stockin)
        db_session.commit()
        
        response = logged_in_client.get('/stock/in/list')
        assert response.status_code == 200

    def test_stockout_list_with_many_records(self, logged_in_client, test_product, db_session):
        """测试大量出库记录列表查询"""
        test_product.current_stock = 10000
        db_session.commit()
        
        # 创建100个出库记录
        for i in range(100):
            stockout = StockOut(
                stockout_no=f'SO-PERF-{i:04d}',
                product_id=test_product.id,
                quantity=5,
                stockout_date=datetime.now()
            )
            db_session.add(stockout)
        db_session.commit()
        
        response = logged_in_client.get('/stock/out/list')
        assert response.status_code == 200


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--cov=app/routes/stock', '--cov-report=term-missing'])
