"""
客户路由测试 - 提高客户路由覆盖率
测试范围：客户列表、创建、编辑、删除、API接口等完整流程
"""
import json
from datetime import datetime

import pytest

try:
    from app import db
    from app.models import Customer, CustomerAccessLog, Order, StockIn, StockOut
    from flask import session
    HAS_FLASK = True
except ImportError:
    HAS_FLASK = False
    session = None
    db = None
    Customer = None
    CustomerAccessLog = None
    Order = None
    StockIn = None
    StockOut = None


@pytest.mark.skipif(not HAS_FLASK, reason="Flask dependencies not available")
class TestCustomerRoutes:
    """客户路由测试"""

    def test_customer_list_get_success(self, logged_in_client, test_customer):
        """测试客户列表页面访问成功"""
        response = logged_in_client.get('/customer/list')
        assert response.status_code == 200
        assert b'customer' in response.data or '客户'.encode() in response.data

    def test_customer_list_post_create_success(self, logged_in_client):
        """测试创建客户成功"""
        data = {
            'name': '新客户',
            'contact': '李四',
            'phone': '13900139000',
            'address': '新地址',
            'note': '测试客户'
        }
        response = logged_in_client.post('/customer/list', data=data, follow_redirects=True)
        assert response.status_code == 200

        # 验证客户创建
        customer = Customer.query.filter_by(name='新客户').first()
        assert customer is not None
        assert customer.contact == '李四'

    def test_customer_list_post_missing_name(self, logged_in_client):
        """测试创建客户缺少名称"""
        data = {
            'contact': '王五',
            'phone': '13800138001'
        }
        response = logged_in_client.post('/customer/list', data=data, follow_redirects=True)
        assert response.status_code == 200
        assert b'error' in response.data or '不能为空'.encode() in response.data

    def test_customer_list_post_duplicate_name(self, logged_in_client, test_customer):
        """测试创建重复名称客户"""
        data = {
            'name': test_customer.name,
            'contact': '测试',
            'phone': '13800138002'
        }
        response = logged_in_client.post('/customer/list', data=data, follow_redirects=True)
        assert response.status_code == 200
        assert b'error' in response.data or '已存在'.encode() in response.data

    def test_customer_edit_get_success(self, logged_in_client, test_customer):
        """测试客户编辑页面访问成功"""
        response = logged_in_client.get(f'/customer/edit/{test_customer.id}')
        assert response.status_code == 200

    def test_customer_edit_post_success(self, logged_in_client, test_customer):
        """测试编辑客户成功"""
        data = {
            'name': '更新客户名',
            'contact': '更新联系人',
            'phone': '13700137000',
            'address': '更新地址',
            'note': '更新备注',
            'status': 'on'
        }
        response = logged_in_client.post(f'/customer/edit/{test_customer.id}', data=data, follow_redirects=True)
        assert response.status_code == 200

        # 验证客户更新
        db.session.refresh(test_customer)
        assert test_customer.name == '更新客户名'
        assert test_customer.contact == '更新联系人'

    def test_customer_edit_post_duplicate_name(self, logged_in_client, test_customer, db_session):
        """测试编辑客户时名称重复"""
        # 创建另一个客户
        other_customer = Customer(
            name='其他客户',
            contact='张三',
            phone='13800138003',
            status=True
        )
        db_session.add(other_customer)
        db_session.commit()

        data = {
            'name': other_customer.name,
            'contact': '测试',
            'phone': '13800138004',
            'status': 'on'
        }
        response = logged_in_client.post(f'/customer/edit/{test_customer.id}', data=data, follow_redirects=True)
        assert response.status_code == 200

    def test_customer_delete_success(self, logged_in_client, db_session):
        """测试删除客户成功"""
        # 创建一个没有关联数据的客户
        customer = Customer(
            name='待删除客户',
            contact='测试',
            phone='13800138005',
            status=True
        )
        db_session.add(customer)
        db_session.commit()

        customer_id = customer.id
        response = logged_in_client.get(f'/customer/delete/{customer_id}', follow_redirects=True)
        assert response.status_code == 200

        # 验证客户删除
        deleted_customer = Customer.query.get(customer_id)
        assert deleted_customer is None

    def test_customer_delete_with_orders(self, logged_in_client, test_customer, test_product, db_session):
        """测试删除有关联订单的客户"""
        # 创建关联订单
        order = Order(
            order_no='ORD-CUST-001',
            product_id=test_product.id,
            customer=test_customer.name,
            quantity=10,
            order_date=datetime.now(),
            status='待备货'
        )
        db_session.add(order)
        db_session.commit()

        response = logged_in_client.get(f'/customer/delete/{test_customer.id}', follow_redirects=True)
        assert response.status_code == 200
        assert b'error' in response.data or '无法删除'.encode() in response.data

    def test_customer_delete_not_found(self, logged_in_client):
        """测试删除不存在的客户"""
        response = logged_in_client.get('/customer/delete/99999', follow_redirects=True)
        assert response.status_code == 404

    def test_customer_toggle_status_success(self, logged_in_client, test_customer):
        """测试切换客户状态成功"""
        original_status = test_customer.status

        response = logged_in_client.get(f'/customer/toggle-status/{test_customer.id}')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data['success'] is True
        assert data['status'] != original_status


@pytest.mark.skipif(not HAS_FLASK, reason="Flask dependencies not available")
class TestCustomerAPIRoutes:
    """客户API路由测试"""

    def test_customer_api_list_all(self, logged_in_client, test_customer):
        """测试获取所有客户列表"""
        response = logged_in_client.get('/customer/api/list')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert isinstance(data, list)
        assert len(data) > 0

    def test_customer_api_list_active(self, logged_in_client, test_customer):
        """测试获取启用客户列表"""
        response = logged_in_client.get('/customer/api/list?status=active')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert isinstance(data, list)
        for customer in data:
            assert customer['status'] is True

    def test_customer_api_list_inactive(self, logged_in_client, db_session):
        """测试获取禁用客户列表"""
        # 创建禁用客户
        customer = Customer(
            name='禁用客户',
            contact='测试',
            phone='13800138006',
            status=False
        )
        db_session.add(customer)
        db_session.commit()

        response = logged_in_client.get('/customer/api/list?status=inactive')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert isinstance(data, list)
        for c in data:
            assert c['status'] is False

    def test_customer_api_search_by_name(self, logged_in_client, test_customer):
        """测试按名称搜索客户"""
        response = logged_in_client.get(f'/customer/api/search?q={test_customer.name}')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert isinstance(data, list)
        assert len(data) > 0

    def test_customer_api_search_by_contact(self, logged_in_client, test_customer):
        """测试按联系人搜索客户"""
        response = logged_in_client.get(f'/customer/api/search?q={test_customer.contact}')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert isinstance(data, list)

    def test_customer_api_search_by_phone(self, logged_in_client, test_customer):
        """测试按电话搜索客户"""
        response = logged_in_client.get(f'/customer/api/search?q={test_customer.phone}')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert isinstance(data, list)

    def test_customer_api_search_empty_query(self, logged_in_client):
        """测试空查询搜索客户"""
        response = logged_in_client.get('/customer/api/search?q=')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert isinstance(data, list)
        assert len(data) == 0

    def test_customer_api_active_names(self, logged_in_client, test_customer):
        """测试获取启用客户名称列表"""
        response = logged_in_client.get('/customer/api/active-names')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert isinstance(data, list)
        for customer in data:
            assert 'id' in customer
            assert 'name' in customer

    def test_customer_api_access_stats(self, logged_in_client, test_customer, db_session):
        """测试获取客户接入统计"""
        # 创建接入日志
        log = CustomerAccessLog(
            customer_name=test_customer.name,
            module='订单',
            operation='创建',
            quantity=10,
            status='success',
            access_time=datetime.now()
        )
        db_session.add(log)
        db_session.commit()

        response = logged_in_client.get('/customer/api/access-stats?days=30')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert 'total_access' in data
        assert 'success_count' in data
        assert 'failed_count' in data

    def test_customer_api_access_stats_by_module(self, logged_in_client, test_customer, db_session):
        """测试按模块获取客户接入统计"""
        # 创建不同模块的接入日志
        for module in ['订单', '备货', '出货']:
            log = CustomerAccessLog(
                customer_name=test_customer.name,
                module=module,
                operation='创建',
                quantity=10,
                status='success',
                access_time=datetime.now()
            )
            db_session.add(log)
        db_session.commit()

        response = logged_in_client.get('/customer/api/access-stats?module=订单')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data['total_access'] > 0

    def test_customer_api_customer_stats(self, logged_in_client, test_customer, db_session):
        """测试获取单个客户统计"""
        # 创建接入日志
        log = CustomerAccessLog(
            customer_name=test_customer.name,
            module='订单',
            operation='创建',
            quantity=20,
            status='success',
            access_time=datetime.now()
        )
        db_session.add(log)
        db_session.commit()

        response = logged_in_client.get(f'/customer/api/customer-stats/{test_customer.id}?days=30')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert 'total_quantity' in data

    def test_customer_api_sync_check(self, logged_in_client, test_customer, db_session):
        """测试客户数据同步检查"""
        response = logged_in_client.get('/customer/api/sync-check')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert 'total_customers' in data
        assert 'active_customers' in data
        assert 'module_status' in data


@pytest.mark.skipif(not HAS_FLASK, reason="Flask dependencies not available")
class TestCustomerBusinessLogic:
    """客户业务逻辑测试"""

    def test_customer_cache_invalidation_on_create(self, logged_in_client, app):
        """测试创建客户时缓存失效"""
        from utils.redis_cache import redis_cache

        # 创建客户
        data = {
            'name': '缓存测试客户',
            'contact': '测试',
            'phone': '13800138007'
        }
        logged_in_client.post('/customer/list', data=data, follow_redirects=True)

        # 验证缓存已清除
        cached_customers = redis_cache.get('customer_list_all')
        assert cached_customers is None

    def test_customer_cache_invalidation_on_edit(self, logged_in_client, test_customer):
        """测试编辑客户时缓存失效"""
        from utils.redis_cache import redis_cache

        data = {
            'name': '编辑后客户名',
            'contact': '测试',
            'phone': '13800138008',
            'status': 'on'
        }
        logged_in_client.post(f'/customer/edit/{test_customer.id}', data=data, follow_redirects=True)

        # 验证缓存已清除
        cached_customers = redis_cache.get('customer_list_all')
        assert cached_customers is None

    def test_customer_status_toggle(self, logged_in_client, test_customer):
        """测试客户状态切换"""
        original_status = test_customer.status

        # 切换状态
        logged_in_client.get(f'/customer/toggle-status/{test_customer.id}')
        db.session.refresh(test_customer)
        assert test_customer.status != original_status

        # 再次切换
        logged_in_client.get(f'/customer/toggle-status/{test_customer.id}')
        db.session.refresh(test_customer)
        assert test_customer.status == original_status


@pytest.mark.skipif(not HAS_FLASK, reason="Flask dependencies not available")
class TestCustomerEdgeCases:
    """客户边界条件测试"""

    def test_customer_with_long_name(self, logged_in_client):
        """测试长客户名称"""
        data = {
            'name': 'A' * 100,
            'contact': '测试',
            'phone': '13800138009'
        }
        response = logged_in_client.post('/customer/list', data=data, follow_redirects=True)
        assert response.status_code == 200

    def test_customer_with_special_characters(self, logged_in_client):
        """测试特殊字符客户名称"""
        data = {
            'name': '客户@#$%^&*()测试',
            'contact': '测试',
            'phone': '13800138010'
        }
        response = logged_in_client.post('/customer/list', data=data, follow_redirects=True)
        assert response.status_code == 200

    def test_customer_with_empty_contact(self, logged_in_client):
        """测试空联系人"""
        data = {
            'name': '无联系人客户',
            'contact': '',
            'phone': '13800138011'
        }
        response = logged_in_client.post('/customer/list', data=data, follow_redirects=True)
        assert response.status_code == 200

    def test_customer_with_empty_phone(self, logged_in_client):
        """测试空电话"""
        data = {
            'name': '无电话客户',
            'contact': '测试',
            'phone': ''
        }
        response = logged_in_client.post('/customer/list', data=data, follow_redirects=True)
        assert response.status_code == 200

    def test_customer_with_invalid_phone_format(self, logged_in_client):
        """测试无效电话格式"""
        data = {
            'name': '无效电话客户',
            'contact': '测试',
            'phone': '123456'  # 无效格式
        }
        response = logged_in_client.post('/customer/list', data=data, follow_redirects=True)
        assert response.status_code == 200


@pytest.mark.skipif(not HAS_FLASK, reason="Flask dependencies not available")
class TestCustomerPerformance:
    """客户性能测试"""

    def test_customer_list_with_many_customers(self, logged_in_client, db_session):
        """测试大量客户列表查询"""
        # 创建100个客户
        for i in range(100):
            customer = Customer(
                name=f'性能测试客户{i}',
                contact=f'联系人{i}',
                phone=f'13800138{i:03d}',
                status=True
            )
            db_session.add(customer)
        db_session.commit()

        response = logged_in_client.get('/customer/list')
        assert response.status_code == 200

    def test_customer_api_search_performance(self, logged_in_client, db_session):
        """测试客户搜索性能"""
        # 创建大量客户
        for i in range(200):
            customer = Customer(
                name=f'搜索测试客户{i}',
                contact=f'联系人{i}',
                phone=f'13900139{i:03d}',
                status=True
            )
            db_session.add(customer)
        db_session.commit()

        # 搜索特定客户
        response = logged_in_client.get('/customer/api/search?q=搜索测试客户100')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert isinstance(data, list)


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--cov=app/routes/customer', '--cov-report=term-missing'])
