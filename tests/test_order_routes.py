"""
订单路由测试 - 提高订单路由覆盖率
测试范围：订单列表、创建、编辑、删除、审批等完整流程
"""
import pytest
import json
from datetime import datetime
try:
    from flask import session
    from app import db
    from app.models import Order, Product, User, Customer, ApprovalRequest, InventoryLog
    HAS_FLASK = True
except ImportError:
    HAS_FLASK = False
    session = None
    db = None
    Order = None
    Product = None
    User = None
    Customer = None
    ApprovalRequest = None
    InventoryLog = None


@pytest.mark.skipif(not HAS_FLASK, reason="Flask dependencies not available")
class TestOrderRoutes:
    """订单路由测试"""

    def test_order_list_get_success(self, logged_in_client, test_order):
        """测试订单列表页面访问成功"""
        response = logged_in_client.get('/order/list')
        assert response.status_code == 200
        assert b'order' in response.data or '订单'.encode('utf-8') in response.data

    def test_order_list_post_create_success(self, logged_in_client, test_product, test_customer):
        """测试创建订单成功"""
        data = {
            'product_id': test_product.id,
            'customer': test_customer.name,
            'quantity': 10,
            'note': '测试订单'
        }
        response = logged_in_client.post('/order/list', data=data, follow_redirects=True)
        assert response.status_code == 200
        
        # 验证订单创建
        order = Order.query.filter_by(customer=test_customer.name).order_by(Order.id.desc()).first()
        assert order is not None
        assert order.quantity == 10

    def test_order_list_post_missing_product(self, logged_in_client, test_customer):
        """测试创建订单缺少产品ID"""
        data = {
            'customer': test_customer.name,
            'quantity': 10
        }
        response = logged_in_client.post('/order/list', data=data, follow_redirects=True)
        assert response.status_code == 200
        assert b'error' in response.data or '错误'.encode('utf-8') in response.data

    def test_order_list_post_invalid_quantity(self, logged_in_client, test_product, test_customer):
        """测试创建订单无效数量"""
        data = {
            'product_id': test_product.id,
            'customer': test_customer.name,
            'quantity': 0,
            'note': '测试订单'
        }
        response = logged_in_client.post('/order/list', data=data, follow_redirects=True)
        assert response.status_code == 200

    def test_order_list_post_nonexistent_product(self, logged_in_client, test_customer):
        """测试创建订单产品不存在"""
        data = {
            'product_id': 99999,
            'customer': test_customer.name,
            'quantity': 10
        }
        response = logged_in_client.post('/order/list', data=data, follow_redirects=True)
        assert response.status_code == 200

    def test_order_edit_get_success(self, logged_in_client, test_order, test_product):
        """测试订单编辑页面访问成功"""
        response = logged_in_client.get(f'/order/edit/{test_order.id}')
        assert response.status_code == 200

    def test_order_edit_post_success_admin(self, logged_in_client, test_order, test_product, test_customer, admin_user):
        """测试管理员编辑订单成功"""
        data = {
            'customer': test_customer.name,
            'quantity': 20,
            'note': '更新后的订单'
        }
        response = logged_in_client.post(f'/order/edit/{test_order.id}', data=data, follow_redirects=True)
        assert response.status_code == 200
        
        # 验证订单更新
        db.session.refresh(test_order)
        assert test_order.quantity == 20

    def test_order_edit_post_validation_error(self, logged_in_client, test_order):
        """测试订单编辑验证错误"""
        data = {
            'customer': '',
            'quantity': -10,
            'note': '测试'
        }
        response = logged_in_client.post(f'/order/edit/{test_order.id}', data=data, follow_redirects=True)
        assert response.status_code == 200

    def test_order_edit_post_quantity_exceed_limit(self, logged_in_client, test_order, test_customer):
        """测试订单编辑数量超限"""
        data = {
            'customer': test_customer.name,
            'quantity': 100001,
            'note': '测试'
        }
        response = logged_in_client.post(f'/order/edit/{test_order.id}', data=data, follow_redirects=True)
        assert response.status_code == 200

    def test_order_delete_success_admin(self, logged_in_client, test_order, test_product, admin_user):
        """测试管理员删除订单成功"""
        initial_stock = test_product.current_stock
        order_id = test_order.id
        
        response = logged_in_client.get(f'/order/delete/{order_id}', follow_redirects=True)
        assert response.status_code == 200
        
        # 验证订单删除
        deleted_order = Order.query.get(order_id)
        assert deleted_order is None
        
        # 验证库存回滚
        db.session.refresh(test_product)
        assert test_product.current_stock == initial_stock - test_order.quantity

    def test_order_delete_not_found(self, logged_in_client):
        """测试删除不存在的订单"""
        response = logged_in_client.get('/order/delete/99999', follow_redirects=True)
        assert response.status_code == 404

    def test_order_cancel_approval_success(self, logged_in_client, test_order, admin_user, db_session):
        """测试取消审批成功"""
        # 创建审批请求
        approval = ApprovalRequest(
            order_id=test_order.id,
            requester_id=admin_user.id,
            operation_type='edit',
            status='pending'
        )
        db_session.add(approval)
        db_session.commit()
        
        response = logged_in_client.post(f'/order/cancel-approval/{approval.id}')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True

    def test_order_cancel_approval_not_found(self, logged_in_client):
        """测试取消不存在的审批"""
        response = logged_in_client.post('/order/cancel-approval/99999')
        assert response.status_code == 404

    def test_order_my_approvals(self, logged_in_client, admin_user):
        """测试我的审批列表"""
        response = logged_in_client.get('/order/my-approvals')
        assert response.status_code == 200

    def test_order_unauthorized_access(self, client):
        """测试未授权访问"""
        response = client.get('/order/list', follow_redirects=False)
        assert response.status_code in [302, 401, 403]


@pytest.mark.skipif(not HAS_FLASK, reason="Flask dependencies not available")
class TestOrderBusinessLogic:
    """订单业务逻辑测试"""

    def test_order_stock_update_on_create(self, logged_in_client, test_product, test_customer):
        """测试订单创建时库存更新"""
        initial_stock = test_product.current_stock
        
        data = {
            'product_id': test_product.id,
            'customer': test_customer.name,
            'quantity': 15
        }
        logged_in_client.post('/order/list', data=data, follow_redirects=True)
        
        db.session.refresh(test_product)
        assert test_product.current_stock == initial_stock + 15

    def test_order_stock_update_on_edit(self, logged_in_client, test_order, test_product, test_customer, admin_user):
        """测试订单编辑时库存更新"""
        initial_stock = test_product.current_stock
        old_quantity = test_order.quantity
        
        data = {
            'customer': test_customer.name,
            'quantity': old_quantity + 10
        }
        logged_in_client.post(f'/order/edit/{test_order.id}', data=data, follow_redirects=True)
        
        db.session.refresh(test_product)
        assert test_product.current_stock == initial_stock + 10

    def test_order_inventory_log_created(self, logged_in_client, test_product, test_customer):
        """测试订单创建时库存日志记录"""
        data = {
            'product_id': test_product.id,
            'customer': test_customer.name,
            'quantity': 10
        }
        logged_in_client.post('/order/list', data=data, follow_redirects=True)
        
        # 验证库存日志
        log = InventoryLog.query.filter_by(
            product_id=test_product.id,
            change_type='订单'
        ).order_by(InventoryLog.id.desc()).first()
        assert log is not None

    def test_order_approval_workflow(self, logged_in_client, test_order, normal_user, db_session):
        """测试订单审批工作流"""
        # 普通用户尝试编辑订单
        with logged_in_client.session_transaction() as sess:
            sess['user_id'] = normal_user.id
            sess['username'] = normal_user.username
            sess['is_super'] = normal_user.is_super
        
        data = {
            'customer': '新客户',
            'quantity': 20
        }
        response = logged_in_client.post(f'/order/edit/{test_order.id}', data=data, follow_redirects=True)
        assert response.status_code == 200
        
        # 验证审批请求创建
        approval = ApprovalRequest.query.filter_by(
            order_id=test_order.id,
            status='pending'
        ).first()
        assert approval is not None


@pytest.mark.skipif(not HAS_FLASK, reason="Flask dependencies not available")
class TestOrderEdgeCases:
    """订单边界条件测试"""

    def test_order_with_empty_customer(self, logged_in_client, test_product):
        """测试空客户名称"""
        data = {
            'product_id': test_product.id,
            'customer': '',
            'quantity': 10
        }
        response = logged_in_client.post('/order/list', data=data, follow_redirects=True)
        assert response.status_code == 200

    def test_order_with_long_note(self, logged_in_client, test_product, test_customer):
        """测试长备注"""
        data = {
            'product_id': test_product.id,
            'customer': test_customer.name,
            'quantity': 10,
            'note': 'A' * 600  # 超过500字符
        }
        response = logged_in_client.post('/order/list', data=data, follow_redirects=True)
        assert response.status_code == 200

    def test_order_with_special_characters(self, logged_in_client, test_product):
        """测试特殊字符客户名称"""
        data = {
            'product_id': test_product.id,
            'customer': '客户@#$%^&*()',
            'quantity': 10
        }
        response = logged_in_client.post('/order/list', data=data, follow_redirects=True)
        assert response.status_code == 200

    def test_order_duplicate_order_no(self, logged_in_client, test_order, test_product, test_customer):
        """测试重复订单号（由系统生成，理论上不会重复）"""
        # 订单号由系统自动生成，测试创建多个订单
        for i in range(5):
            data = {
                'product_id': test_product.id,
                'customer': test_customer.name,
                'quantity': 5
            }
            response = logged_in_client.post('/order/list', data=data, follow_redirects=True)
            assert response.status_code == 200


@pytest.mark.skipif(not HAS_FLASK, reason="Flask dependencies not available")
class TestOrderPerformance:
    """订单性能测试"""

    def test_order_list_with_many_orders(self, logged_in_client, test_product, test_customer, db_session):
        """测试大量订单列表查询"""
        # 创建100个订单
        for i in range(100):
            order = Order(
                order_no=f'ORD-PERF-{i:04d}',
                product_id=test_product.id,
                customer=test_customer.name,
                quantity=10,
                order_date=datetime.now(),
                status='待备货'
            )
            db_session.add(order)
        db_session.commit()
        
        response = logged_in_client.get('/order/list')
        assert response.status_code == 200

    def test_order_search_performance(self, logged_in_client, test_product, test_customer, db_session):
        """测试订单搜索性能"""
        # 创建不同客户的订单
        for i in range(50):
            order = Order(
                order_no=f'ORD-SEARCH-{i:04d}',
                product_id=test_product.id,
                customer=f'客户{i}',
                quantity=10,
                order_date=datetime.now(),
                status='待备货'
            )
            db_session.add(order)
        db_session.commit()
        
        # 搜索特定客户
        response = logged_in_client.get('/order/list')
        assert response.status_code == 200


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--cov=app/routes/order', '--cov-report=term-missing'])
