"""
API路由测试 - 全面覆盖所有API端点
测试范围：健康检查、产品搜索、库存查询、批量操作等

状态: 被测目标已删除，全部用例显式 skip（原 `flask_legacy` 标记已摘除）。
"""
import json
from datetime import datetime

import pytest

# 被测目标已不存在：根目录 Flask 应用 `app`（`from app import db` / `from app.models import ...`）
# 在 Flask→FastAPI 迁移中被整体删除（最后出现于 commit c3aa5831），这些用例无法通过。
# 原先的 `flask_legacy` 标记配合 CI 的 `-m "not flask_legacy"` 会把本文件整体反选，
# 连 skip 记录都不可见 —— 那是掩盖而非挂起。现改为显式 skip，CI 如实报告条数与原因。
# 跟踪项：按 FastAPI 路由 + httpx.AsyncClient 重写（参考 tests/e2e_api/ 的既有实现）。
pytestmark = pytest.mark.skip(
    reason="被测目标缺失：根 app/（Flask 应用）已删除，from app import db 必然失败；"
           "需按 FastAPI + httpx.AsyncClient 重写（参考 tests/e2e_api/）"
)

try:
    from app import db
    from app.models import Customer, InventoryLog, Order, Product, StockIn, StockOut, User
    from flask import session
    HAS_FLASK = True
except ImportError:
    HAS_FLASK = False
    session = None
    db = None
    Product = None
    Order = None
    StockIn = None
    StockOut = None
    InventoryLog = None
    User = None
    Customer = None

try:
    from utils.validators import OrderValidator, ProductValidator, Validator
    HAS_VALIDATORS = True
except ImportError:
    HAS_VALIDATORS = False
    Validator = None
    ProductValidator = None
    OrderValidator = None


@pytest.mark.skipif(not HAS_FLASK, reason="Flask dependencies not available")
class TestHealthCheckAPI:
    """健康检查API测试"""

    def test_health_check_success(self, client):
        """测试健康检查成功"""
        response = client.get('/api/health')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'ok'
        assert data['db'] == 'connected'

    def test_health_check_with_db_error(self, app, client, monkeypatch):
        """测试数据库错误时的健康检查"""
        def mock_execute(*args, **kwargs):
            raise Exception("Database connection failed")

        # 模拟数据库错误
        with app.app_context():
            monkeypatch.setattr(db.session, 'execute', mock_execute)
            response = client.get('/api/health')
            assert response.status_code == 500
            data = json.loads(response.data)
            assert data['status'] == 'error'
            assert data['db'] == 'disconnected'


@pytest.mark.skipif(not HAS_FLASK, reason="Flask dependencies not available")
class TestProductSearchAPI:
    """产品搜索API测试"""

    def test_product_search_by_name(self, logged_in_client, test_products):
        """测试按名称搜索产品"""
        response = logged_in_client.get('/api/product-search?q=测试产品1')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert isinstance(data, list)
        assert len(data) > 0
        assert '测试产品1' in data[0]['name']

    def test_product_search_by_barcode(self, logged_in_client, test_product):
        """测试按条码搜索产品"""
        response = logged_in_client.get(f'/api/product-search?q={test_product.barcode}')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert isinstance(data, list)
        assert len(data) > 0
        assert data[0]['barcode'] == test_product.barcode

    def test_product_search_empty_query(self, logged_in_client, test_products):
        """测试空查询返回所有产品"""
        response = logged_in_client.get('/api/product-search?q=')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert isinstance(data, list)

    def test_product_search_no_results(self, logged_in_client):
        """测试无结果搜索"""
        response = logged_in_client.get('/api/product-search?q=不存在的产品')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert isinstance(data, list)
        assert len(data) == 0

    def test_product_search_unauthorized(self, client):
        """测试未授权访问"""
        response = client.get('/api/product-search?q=test')
        # 应该返回401或重定向到登录页
        assert response.status_code in [401, 302, 403]


@pytest.mark.skipif(not HAS_FLASK, reason="Flask dependencies not available")
class TestProductAvailableStockAPI:
    """产品可用库存API测试"""

    def test_get_available_stock_success(self, logged_in_client, test_product):
        """测试获取可用库存成功"""
        response = logged_in_client.get(f'/api/product-available-stock?product_id={test_product.id}')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['product_id'] == test_product.id
        assert data['name'] == test_product.name
        assert 'current_stock' in data
        assert 'available_stock' in data

    def test_get_available_stock_invalid_id(self, logged_in_client):
        """测试无效产品ID"""
        response = logged_in_client.get('/api/product-available-stock?product_id=99999')
        assert response.status_code == 404

    def test_get_available_stock_missing_id(self, logged_in_client):
        """测试缺少产品ID参数"""
        response = logged_in_client.get('/api/product-available-stock')
        assert response.status_code == 400

    def test_get_available_stock_non_integer_id(self, logged_in_client):
        """测试非整数产品ID"""
        response = logged_in_client.get('/api/product-available-stock?product_id=abc')
        assert response.status_code == 400


@pytest.mark.skipif(not HAS_FLASK, reason="Flask dependencies not available")
class TestInventoryLogsAPI:
    """库存日志API测试"""

    def test_get_inventory_logs_success(self, logged_in_client, test_product, db_session):
        """测试获取库存日志成功"""
        # 创建库存日志
        log = InventoryLog(
            product_id=test_product.id,
            change_type='入库',
            change_quantity=50,
            change_date=datetime.now(),
            note='测试日志'
        )
        db_session.add(log)
        db_session.commit()

        response = logged_in_client.get(f'/api/inventory-logs/{test_product.id}')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert isinstance(data, list)
        assert len(data) > 0
        assert data[0]['change_type'] == '入库'

    def test_get_inventory_logs_empty(self, logged_in_client, test_product):
        """测试获取空库存日志"""
        response = logged_in_client.get(f'/api/inventory-logs/{test_product.id}')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert isinstance(data, list)
        assert len(data) == 0


@pytest.mark.skipif(not HAS_FLASK, reason="Flask dependencies not available")
class TestAvailableStockinsAPI:
    """可用入库记录API测试"""

    def test_get_available_stockins_success(self, logged_in_client, test_stockin):
        """测试获取可用入库记录成功"""
        response = logged_in_client.get('/api/available-stockins')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert isinstance(data, list)
        assert len(data) > 0

    def test_get_available_stockins_by_product(self, logged_in_client, test_stockin, test_product):
        """测试按产品筛选入库记录"""
        response = logged_in_client.get(f'/api/available-stockins?product_id={test_product.id}')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert isinstance(data, list)
        for item in data:
            assert item['product_id'] == test_product.id

    def test_get_available_stockins_by_customer(self, logged_in_client, test_stockin, test_customer):
        """测试按客户筛选入库记录"""
        response = logged_in_client.get(f'/api/available-stockins?customer={test_customer.name}')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert isinstance(data, list)

    def test_get_available_stockins_invalid_product_id(self, logged_in_client):
        """测试无效产品ID"""
        response = logged_in_client.get('/api/available-stockins?product_id=abc')
        assert response.status_code == 400


@pytest.mark.skipif(not HAS_FLASK, reason="Flask dependencies not available")
class TestStockinInfoAPI:
    """入库信息API测试"""

    def test_get_stockin_info_success(self, logged_in_client, test_stockin):
        """测试获取入库信息成功"""
        response = logged_in_client.get(f'/api/stockin-info/{test_stockin.id}')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['id'] == test_stockin.id
        assert data['quantity'] == test_stockin.quantity

    def test_get_stockin_info_not_found(self, logged_in_client):
        """测试入库记录不存在"""
        response = logged_in_client.get('/api/stockin-info/99999')
        assert response.status_code == 404


@pytest.mark.skipif(not HAS_FLASK, reason="Flask dependencies not available")
class TestBatchSubmitOrdersAPI:
    """批量提交订单API测试"""

    def test_batch_submit_orders_success(self, logged_in_client, test_product, test_customer):
        """测试批量提交订单成功"""
        orders_data = {
            'orders': [
                {
                    'product_id': test_product.id,
                    'customer': test_customer.name,
                    'quantity': 10,
                    'note': '测试订单1'
                },
                {
                    'product_id': test_product.id,
                    'customer': test_customer.name,
                    'quantity': 20,
                    'note': '测试订单2'
                }
            ]
        }

        response = logged_in_client.post(
            '/api/batch-submit-orders',
            data=json.dumps(orders_data),
            content_type='application/json'
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert len(data['results']) == 2

    def test_batch_submit_orders_missing_fields(self, logged_in_client, test_product):
        """测试缺少必填字段"""
        orders_data = {
            'orders': [
                {
                    'product_id': test_product.id,
                    # 缺少customer和quantity
                }
            ]
        }

        response = logged_in_client.post(
            '/api/batch-submit-orders',
            data=json.dumps(orders_data),
            content_type='application/json'
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert data['results'][0]['success'] is False

    def test_batch_submit_orders_invalid_product(self, logged_in_client, test_customer):
        """测试无效产品ID"""
        orders_data = {
            'orders': [
                {
                    'product_id': 99999,
                    'customer': test_customer.name,
                    'quantity': 10
                }
            ]
        }

        response = logged_in_client.post(
            '/api/batch-submit-orders',
            data=json.dumps(orders_data),
            content_type='application/json'
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['results'][0]['success'] is False

    def test_batch_submit_orders_with_deduction(self, logged_in_client, test_product, test_customer, test_stockin):
        """测试带抵扣的订单提交"""
        orders_data = {
            'orders': [
                {
                    'product_id': test_product.id,
                    'customer': test_customer.name,
                    'quantity': 10,
                    'deduct_stock': 'on',
                    'deductible_quantity': 5
                }
            ]
        }

        response = logged_in_client.post(
            '/api/batch-submit-orders',
            data=json.dumps(orders_data),
            content_type='application/json'
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True


@pytest.mark.skipif(not HAS_FLASK, reason="Flask dependencies not available")
class TestBatchSubmitStockinsAPI:
    """批量提交入库API测试"""

    def test_batch_submit_stockins_success(self, logged_in_client, test_product, test_customer):
        """测试批量提交入库成功"""
        stockins_data = {
            'stockins': [
                {
                    'product_id': test_product.id,
                    'customer': test_customer.name,
                    'quantity': 50,
                    'note': '测试入库1'
                },
                {
                    'product_id': test_product.id,
                    'customer': test_customer.name,
                    'quantity': 30,
                    'note': '测试入库2'
                }
            ]
        }

        response = logged_in_client.post(
            '/api/batch-submit-stockins',
            data=json.dumps(stockins_data),
            content_type='application/json'
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert len(data['results']) == 2

    def test_batch_submit_stockins_missing_fields(self, logged_in_client, test_product):
        """测试缺少必填字段"""
        stockins_data = {
            'stockins': [
                {
                    'product_id': test_product.id,
                    # 缺少customer和quantity
                }
            ]
        }

        response = logged_in_client.post(
            '/api/batch-submit-stockins',
            data=json.dumps(stockins_data),
            content_type='application/json'
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['results'][0]['success'] is False

    def test_batch_submit_stockins_invalid_product(self, logged_in_client, test_customer):
        """测试无效产品ID"""
        stockins_data = {
            'stockins': [
                {
                    'product_id': 99999,
                    'customer': test_customer.name,
                    'quantity': 50
                }
            ]
        }

        response = logged_in_client.post(
            '/api/batch-submit-stockins',
            data=json.dumps(stockins_data),
            content_type='application/json'
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['results'][0]['success'] is False


@pytest.mark.skipif(not HAS_FLASK, reason="Flask dependencies not available")
class TestBatchSubmitStockoutsAPI:
    """批量提交出库API测试"""

    def test_batch_submit_stockouts_success(self, logged_in_client, test_product):
        """测试批量提交出库成功"""
        # 先确保有足够库存
        test_product.current_stock = 1000
        db.session.commit()

        stockouts_data = {
            'stockouts': [
                {
                    'product_id': test_product.id,
                    'quantity': 10,
                    'customer': '客户A',
                    'note': '测试出库1'
                },
                {
                    'product_id': test_product.id,
                    'quantity': 20,
                    'customer': '客户B',
                    'note': '测试出库2'
                }
            ]
        }

        response = logged_in_client.post(
            '/api/batch-submit-stockouts',
            data=json.dumps(stockouts_data),
            content_type='application/json'
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert len(data['results']) == 2

    def test_batch_submit_stockouts_insufficient_stock(self, logged_in_client, test_product):
        """测试库存不足"""
        test_product.current_stock = 5
        db.session.commit()

        stockouts_data = {
            'stockouts': [
                {
                    'product_id': test_product.id,
                    'quantity': 100,
                    'customer': '客户A'
                }
            ]
        }

        response = logged_in_client.post(
            '/api/batch-submit-stockouts',
            data=json.dumps(stockouts_data),
            content_type='application/json'
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['results'][0]['success'] is False
        assert '库存不足' in data['results'][0]['error']

    def test_batch_submit_stockouts_missing_fields(self, logged_in_client, test_product):
        """测试缺少必填字段"""
        stockouts_data = {
            'stockouts': [
                {
                    'product_id': test_product.id,
                    # 缺少quantity
                }
            ]
        }

        response = logged_in_client.post(
            '/api/batch-submit-stockouts',
            data=json.dumps(stockouts_data),
            content_type='application/json'
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['results'][0]['success'] is False


@pytest.mark.skipif(not HAS_FLASK, reason="Flask dependencies not available")
class TestLogOperationAPI:
    """操作日志API测试"""

    def test_log_operation_success(self, client):
        """测试记录操作日志成功"""
        log_data = {
            'operation': 'test_operation',
            'details': '测试操作详情'
        }

        response = client.post(
            '/api/log-operation',
            data=json.dumps(log_data),
            content_type='application/json'
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True

    def test_log_operation_invalid_json(self, client):
        """测试无效JSON数据"""
        response = client.post(
            '/api/log-operation',
            data='invalid json',
            content_type='application/json'
        )
        assert response.status_code in [400, 500]


@pytest.mark.skipif(not HAS_VALIDATORS, reason="Validator dependencies not available")
class TestValidatorIntegration:
    """验证器集成测试"""

    def test_validator_required_field(self):
        """测试必填字段验证"""
        validator = Validator()

        # 有效值
        assert validator.validate_required('test', '字段') is True

        # 空值
        assert validator.validate_required('', '字段') is False

        # None
        assert validator.validate_required(None, '字段') is False

    def test_validator_string_length(self):
        """测试字符串长度验证"""
        validator = Validator()

        # 有效长度
        assert validator.validate_string('test', '字段', min_length=1, max_length=10) is True

        # 过短
        validator2 = Validator()
        assert validator2.validate_string('ab', '字段', min_length=3) is False

        # 过长
        validator3 = Validator()
        assert validator3.validate_string('abcdefghijk', '字段', max_length=10) is False

    def test_validator_integer_range(self):
        """测试整数范围验证"""
        validator = Validator()

        # 有效整数
        assert validator.validate_integer(10, '字段', min_value=1, max_value=100) is True

        # 过小
        validator2 = Validator()
        assert validator2.validate_integer(0, '字段', min_value=1) is False

        # 过大
        validator3 = Validator()
        assert validator3.validate_integer(101, '字段', max_value=100) is False

    def test_product_validator(self):
        """测试产品验证器"""
        validator = ProductValidator()

        # 有效数据
        valid_data = {
            'name': '测试产品',
            'barcode': 'BC001',
            'initial_stock': 100
        }
        assert validator.validate_create(valid_data) is True

        # 无效数据
        validator2 = ProductValidator()
        invalid_data = {
            'name': '',
            'barcode': '',
            'initial_stock': -1
        }
        assert validator2.validate_create(invalid_data) is False

    def test_order_validator(self):
        """测试订单验证器"""
        validator = OrderValidator()

        # 有效数据
        valid_data = {
            'order_no': 'ORD001',
            'product_id': 1,
            'quantity': 10,
            'customer': '测试客户'
        }
        assert validator.validate_create(valid_data) is True

        # 无效数据
        validator2 = OrderValidator()
        invalid_data = {
            'order_no': '',
            'product_id': 0,
            'quantity': -1,
            'customer': ''
        }
        assert validator2.validate_create(invalid_data) is False


@pytest.mark.skipif(not HAS_FLASK, reason="Flask dependencies not available")
class TestAPIErrorHandling:
    """API错误处理测试"""

    def test_404_error(self, client):
        """测试404错误"""
        response = client.get('/api/nonexistent-endpoint')
        assert response.status_code == 404

    def test_method_not_allowed(self, logged_in_client, test_product):
        """测试方法不允许"""
        response = logged_in_client.delete('/api/health')
        assert response.status_code == 405

    def test_invalid_json_request(self, logged_in_client):
        """测试无效JSON请求"""
        response = logged_in_client.post(
            '/api/batch-submit-orders',
            data='invalid json data',
            content_type='application/json'
        )
        assert response.status_code in [400, 500]


@pytest.mark.skipif(not HAS_FLASK, reason="Flask dependencies not available")
class TestAPIPerformance:
    """API性能测试"""

    def test_product_search_performance(self, logged_in_client, test_products):
        """测试产品搜索性能"""
        import time

        start_time = time.time()
        response = logged_in_client.get('/api/product-search?q=测试')
        end_time = time.time()

        assert response.status_code == 200
        # 响应时间应小于1秒
        assert (end_time - start_time) < 1.0

    def test_batch_operations_performance(self, logged_in_client, test_product, test_customer):
        """测试批量操作性能"""
        import time

        # 创建100个订单
        orders_data = {
            'orders': [
                {
                    'product_id': test_product.id,
                    'customer': test_customer.name,
                    'quantity': 1
                } for _ in range(100)
            ]
        }

        start_time = time.time()
        response = logged_in_client.post(
            '/api/batch-submit-orders',
            data=json.dumps(orders_data),
            content_type='application/json'
        )
        end_time = time.time()

        assert response.status_code == 200
        # 批量操作应在5秒内完成
        assert (end_time - start_time) < 5.0


@pytest.mark.skipif(not HAS_FLASK, reason="Flask dependencies not available")
class TestAPIDataIntegrity:
    """API数据完整性测试"""

    def test_order_creation_updates_stock(self, logged_in_client, test_product, test_customer):
        """测试订单创建更新库存"""
        initial_stock = test_product.current_stock

        orders_data = {
            'orders': [
                {
                    'product_id': test_product.id,
                    'customer': test_customer.name,
                    'quantity': 10
                }
            ]
        }

        response = logged_in_client.post(
            '/api/batch-submit-orders',
            data=json.dumps(orders_data),
            content_type='application/json'
        )

        assert response.status_code == 200

        # 刷新产品数据
        db.session.refresh(test_product)
        # 订单创建应该增加库存
        assert test_product.current_stock == initial_stock + 10

    def test_stockout_creation_decreases_stock(self, logged_in_client, test_product):
        """测试出库创建减少库存"""
        test_product.current_stock = 100
        db.session.commit()

        stockouts_data = {
            'stockouts': [
                {
                    'product_id': test_product.id,
                    'quantity': 20
                }
            ]
        }

        response = logged_in_client.post(
            '/api/batch-submit-stockouts',
            data=json.dumps(stockouts_data),
            content_type='application/json'
        )

        assert response.status_code == 200

        # 刷新产品数据
        db.session.refresh(test_product)
        assert test_product.current_stock == 80

    def test_inventory_log_created(self, logged_in_client, test_product, test_customer):
        """测试库存日志创建"""
        orders_data = {
            'orders': [
                {
                    'product_id': test_product.id,
                    'customer': test_customer.name,
                    'quantity': 10
                }
            ]
        }

        response = logged_in_client.post(
            '/api/batch-submit-orders',
            data=json.dumps(orders_data),
            content_type='application/json'
        )

        assert response.status_code == 200

        # 检查库存日志
        logs = InventoryLog.query.filter_by(product_id=test_product.id).all()
        assert len(logs) > 0


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--cov=app/routes/api', '--cov-report=term-missing'])
