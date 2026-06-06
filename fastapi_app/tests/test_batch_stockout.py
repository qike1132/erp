"""
批量出库 batch_create_stockouts 单元测试

覆盖场景：
- 正常出库（单条/多条、FIFO 订单分配）
- 库存不足
- 无可用订单
- 出货数量超过可出货量
- 缺少必填字段
- 未选择客户
- 定制订单缺少国家
- 出货数量 <= 0
- 部分成功部分失败
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.services import stock_service


# ==================== 辅助函数 ====================

def _make_product(product_id=1, name="产品A", current_stock=100):
    """构造 mock Product 对象"""
    product = MagicMock()
    product.id = product_id
    product.name = name
    product.current_stock = current_stock
    return product


def _make_shipment_info(available_quantity=50, order_quantity=100, shipped_quantity=50, orders=None):
    """构造 calculate_available_shipment_quantity 的返回值"""
    if orders is None:
        orders = [{'order_id': 1, 'available': available_quantity, 'quantity': order_quantity}]
    return {
        'available_quantity': available_quantity,
        'order_quantity': order_quantity,
        'shipped_quantity': shipped_quantity,
        'orders': orders,
    }


def _make_stockout_data(product_id=1, customer="客户A", quantity=10, order_type='regular', country='', note=''):
    """构造单条出库请求数据"""
    return {
        'product_id': product_id,
        'customer': customer,
        'quantity': quantity,
        'order_type': order_type,
        'country': country,
        'note': note,
        'id': 'test-1',
    }


# ==================== 正常出库 ====================

class TestBatchCreateStockoutsNormal:
    """正常出库场景"""

    async def test_single_stockout_success(self, mock_db):
        """单条出库成功"""
        product = _make_product(current_stock=100)
        shipment_info = _make_shipment_info(available_quantity=50, orders=[
            {'order_id': 1, 'available': 50, 'quantity': 100}
        ])

        with patch('fastapi_app.services.stock_service.get_product_for_update', new_callable=AsyncMock, return_value=product), \
             patch('fastapi_app.services.stock_service.calculate_available_shipment_quantity', new_callable=AsyncMock, return_value=shipment_info), \
             patch('fastapi_app.services.stock_service.generate_stockout_number', new_callable=AsyncMock, return_value='SO-20260603-0001'):

            result = await stock_service.batch_create_stockouts(mock_db, [_make_stockout_data(quantity=10)])

        assert result['success'] is True
        assert len(result['results']) == 1
        assert result['results'][0]['success'] is True
        assert result['results'][0]['stockout_no'] == 'SO-20260603-0001'
        # 验证库存扣减
        assert product.current_stock == 90
        # 验证 db.add 被调用（StockOut + InventoryLog）
        assert mock_db.add.call_count >= 2
        # 验证 flush 被调用
        mock_db.flush.assert_awaited()

    async def test_multiple_stockouts_success(self, mock_db):
        """多条出库全部成功"""
        product1 = _make_product(product_id=1, current_stock=200)
        product2 = _make_product(product_id=2, current_stock=150)
        shipment1 = _make_shipment_info(available_quantity=100, orders=[
            {'order_id': 1, 'available': 100, 'quantity': 100}
        ])
        shipment2 = _make_shipment_info(available_quantity=80, orders=[
            {'order_id': 2, 'available': 80, 'quantity': 80}
        ])

        product_map = {1: product1, 2: product2}
        shipment_map = {(1, '客户A'): shipment1, (2, '客户B'): shipment2}

        async def mock_get_product(db, pid):
            return product_map[pid]

        async def mock_calc_shipment(db, pid, customer, **kwargs):
            return shipment_map[(pid, customer)]

        with patch('fastapi_app.services.stock_service.get_product_for_update', side_effect=mock_get_product), \
             patch('fastapi_app.services.stock_service.calculate_available_shipment_quantity', side_effect=mock_calc_shipment), \
             patch('fastapi_app.services.stock_service.generate_stockout_number', new_callable=AsyncMock, return_value='SO-20260603-0001'):

            data = [
                _make_stockout_data(product_id=1, customer="客户A", quantity=20),
                _make_stockout_data(product_id=2, customer="客户B", quantity=30),
            ]
            result = await stock_service.batch_create_stockouts(mock_db, data)

        assert result['success'] is True
        assert len(result['results']) == 2
        assert all(r['success'] for r in result['results'])
        assert product1.current_stock == 180
        assert product2.current_stock == 120

    async def test_fifo_order_allocation(self, mock_db):
        """FIFO 订单分配：出货量跨多个订单"""
        product = _make_product(current_stock=100)
        shipment_info = _make_shipment_info(available_quantity=60, orders=[
            {'order_id': 1, 'available': 20, 'quantity': 20},
            {'order_id': 2, 'available': 30, 'quantity': 30},
            {'order_id': 3, 'available': 10, 'quantity': 10},
        ])

        stockout_numbers = iter(['SO-001', 'SO-002', 'SO-003'])

        with patch('fastapi_app.services.stock_service.get_product_for_update', new_callable=AsyncMock, return_value=product), \
             patch('fastapi_app.services.stock_service.calculate_available_shipment_quantity', new_callable=AsyncMock, return_value=shipment_info), \
             patch('fastapi_app.services.stock_service.generate_stockout_number', new_callable=AsyncMock, side_effect=lambda *a, **k: next(stockout_numbers)):

            result = await stock_service.batch_create_stockouts(mock_db, [_make_stockout_data(quantity=50)])

        assert result['results'][0]['success'] is True
        # 50 = 20 + 30，前两个订单全部分配，第三个订单不分配
        assert product.current_stock == 50
        # 2 次 StockOut add + 1 次 InventoryLog add = 3
        assert mock_db.add.call_count == 3

    async def test_custom_order_with_country(self, mock_db):
        """定制订单出库成功（带国家）"""
        product = _make_product(current_stock=100)
        shipment_info = _make_shipment_info(available_quantity=30, orders=[
            {'order_id': 10, 'available': 30, 'quantity': 30}
        ])

        with patch('fastapi_app.services.stock_service.get_product_for_update', new_callable=AsyncMock, return_value=product), \
             patch('fastapi_app.services.stock_service.calculate_available_shipment_quantity', new_callable=AsyncMock, return_value=shipment_info), \
             patch('fastapi_app.services.stock_service.generate_stockout_number', new_callable=AsyncMock, return_value='SO-C-001'):

            data = _make_stockout_data(quantity=15, order_type='custom', country='日本')
            result = await stock_service.batch_create_stockouts(mock_db, [data])

        assert result['results'][0]['success'] is True
        assert product.current_stock == 85


# ==================== 库存不足 ====================

class TestBatchCreateStockoutsInsufficientStock:
    """库存不足场景"""

    async def test_insufficient_stock(self, mock_db):
        """库存不足，出库失败"""
        product = _make_product(current_stock=5)

        with patch('fastapi_app.services.stock_service.get_product_for_update', new_callable=AsyncMock, return_value=product):
            result = await stock_service.batch_create_stockouts(mock_db, [_make_stockout_data(quantity=10)])

        assert result['results'][0]['success'] is False
        assert '库存不足' in result['results'][0]['error']
        assert '5' in result['results'][0]['error']

    async def test_zero_stock(self, mock_db):
        """零库存出库"""
        product = _make_product(current_stock=0)

        with patch('fastapi_app.services.stock_service.get_product_for_update', new_callable=AsyncMock, return_value=product):
            result = await stock_service.batch_create_stockouts(mock_db, [_make_stockout_data(quantity=1)])

        assert result['results'][0]['success'] is False
        assert '库存不足' in result['results'][0]['error']


# ==================== 订单数量异常 ====================

class TestBatchCreateStockoutsOrderIssues:
    """订单相关异常场景"""

    async def test_no_available_orders(self, mock_db):
        """客户没有可用订单支持出货"""
        product = _make_product(current_stock=100)
        shipment_info = _make_shipment_info(available_quantity=0, order_quantity=0, shipped_quantity=0, orders=[])

        with patch('fastapi_app.services.stock_service.get_product_for_update', new_callable=AsyncMock, return_value=product), \
             patch('fastapi_app.services.stock_service.calculate_available_shipment_quantity', new_callable=AsyncMock, return_value=shipment_info):

            result = await stock_service.batch_create_stockouts(mock_db, [_make_stockout_data()])

        assert result['results'][0]['success'] is False
        assert '没有可用的订单' in result['results'][0]['error']

    async def test_quantity_exceeds_available(self, mock_db):
        """出货数量超过可出货量"""
        product = _make_product(current_stock=200)
        shipment_info = _make_shipment_info(available_quantity=30, order_quantity=50, shipped_quantity=20, orders=[
            {'order_id': 1, 'available': 30, 'quantity': 50}
        ])

        with patch('fastapi_app.services.stock_service.get_product_for_update', new_callable=AsyncMock, return_value=product), \
             patch('fastapi_app.services.stock_service.calculate_available_shipment_quantity', new_callable=AsyncMock, return_value=shipment_info):

            result = await stock_service.batch_create_stockouts(mock_db, [_make_stockout_data(quantity=50)])

        assert result['results'][0]['success'] is False
        assert '超过可出货量' in result['results'][0]['error']
        # 库存不应被扣减
        assert product.current_stock == 200


# ==================== 输入校验 ====================

class TestBatchCreateStockoutsValidation:
    """输入校验场景"""

    async def test_missing_product_id(self, mock_db):
        """缺少产品ID"""
        data = {'customer': '客户A', 'quantity': 10, 'id': 'test-1'}
        result = await stock_service.batch_create_stockouts(mock_db, [data])
        assert result['results'][0]['success'] is False
        assert '缺少必填字段' in result['results'][0]['error']

    async def test_missing_quantity(self, mock_db):
        """缺少数量"""
        data = {'product_id': 1, 'customer': '客户A', 'id': 'test-1'}
        result = await stock_service.batch_create_stockouts(mock_db, [data])
        assert result['results'][0]['success'] is False
        assert '缺少必填字段' in result['results'][0]['error']

    async def test_missing_customer(self, mock_db):
        """未选择客户"""
        data = _make_stockout_data(customer='')
        result = await stock_service.batch_create_stockouts(mock_db, [data])
        assert result['results'][0]['success'] is False
        assert '出货必须选择客户' in result['results'][0]['error']

    async def test_whitespace_customer(self, mock_db):
        """客户名为纯空格"""
        data = _make_stockout_data(customer='   ')
        result = await stock_service.batch_create_stockouts(mock_db, [data])
        assert result['results'][0]['success'] is False
        assert '出货必须选择客户' in result['results'][0]['error']

    async def test_custom_order_without_country(self, mock_db):
        """定制订单未填写国家"""
        data = _make_stockout_data(order_type='custom', country='')
        result = await stock_service.batch_create_stockouts(mock_db, [data])
        assert result['results'][0]['success'] is False
        assert '定制订单必须填写国家名称' in result['results'][0]['error']

    async def test_zero_quantity(self, mock_db):
        """出货数量为0"""
        data = _make_stockout_data(quantity=0)
        result = await stock_service.batch_create_stockouts(mock_db, [data])
        assert result['results'][0]['success'] is False
        # quantity=0 是 falsy，会被 not all([product_id, quantity]) 拦截为"缺少必填字段"
        assert '缺少必填字段' in result['results'][0]['error'] or '必须大于0' in result['results'][0]['error']

    async def test_negative_quantity(self, mock_db):
        """出货数量为负数"""
        data = _make_stockout_data(quantity=-5)
        result = await stock_service.batch_create_stockouts(mock_db, [data])
        assert result['results'][0]['success'] is False
        assert '必须大于0' in result['results'][0]['error']


# ==================== 部分成功 ====================

class TestBatchCreateStockoutsPartial:
    """部分成功部分失败场景"""

    async def test_partial_success(self, mock_db):
        """多条出库中部分成功部分失败"""
        product_ok = _make_product(product_id=1, current_stock=100)
        product_low = _make_product(product_id=2, current_stock=3)
        shipment_ok = _make_shipment_info(available_quantity=50, orders=[
            {'order_id': 1, 'available': 50, 'quantity': 50}
        ])

        with patch('fastapi_app.services.stock_service.get_product_for_update', new_callable=AsyncMock, side_effect=[product_ok, product_low]), \
             patch('fastapi_app.services.stock_service.calculate_available_shipment_quantity', new_callable=AsyncMock, return_value=shipment_ok), \
             patch('fastapi_app.services.stock_service.generate_stockout_number', new_callable=AsyncMock, return_value='SO-001'):

            data = [
                _make_stockout_data(product_id=1, quantity=10),  # 成功
                _make_stockout_data(product_id=2, quantity=20),  # 库存不足
            ]
            result = await stock_service.batch_create_stockouts(mock_db, data)

        assert result['success'] is True
        assert result['results'][0]['success'] is True
        assert result['results'][1]['success'] is False
        assert '库存不足' in result['results'][1]['error']
        # 第一条成功，库存应扣减
        assert product_ok.current_stock == 90

    async def test_validation_error_and_success_mixed(self, mock_db):
        """校验失败与出库成功混合"""
        product = _make_product(product_id=1, current_stock=100)
        shipment_info = _make_shipment_info(available_quantity=50, orders=[
            {'order_id': 1, 'available': 50, 'quantity': 50}
        ])

        with patch('fastapi_app.services.stock_service.get_product_for_update', new_callable=AsyncMock, return_value=product), \
             patch('fastapi_app.services.stock_service.calculate_available_shipment_quantity', new_callable=AsyncMock, return_value=shipment_info), \
             patch('fastapi_app.services.stock_service.generate_stockout_number', new_callable=AsyncMock, return_value='SO-001'):

            data = [
                {'customer': '客户A', 'quantity': 10, 'id': 'test-1'},  # 缺少 product_id
                _make_stockout_data(product_id=1, quantity=10),          # 成功
            ]
            result = await stock_service.batch_create_stockouts(mock_db, data)

        assert result['results'][0]['success'] is False
        assert result['results'][1]['success'] is True


# ==================== 空数据 ====================

class TestBatchCreateStockoutsEmpty:
    """空数据场景"""

    async def test_empty_list(self, mock_db):
        """空列表"""
        result = await stock_service.batch_create_stockouts(mock_db, [])
        assert result['success'] is True
        assert result['results'] == []

    async def test_all_validation_failed(self, mock_db):
        """所有数据校验都失败"""
        data = [
            {'customer': '', 'quantity': 10, 'id': '1'},     # 缺少 product_id
            {'product_id': 1, 'quantity': 0, 'id': '2'},     # 数量为0
            {'product_id': 1, 'customer': '', 'id': '3'},     # 无客户
        ]
        result = await stock_service.batch_create_stockouts(mock_db, data)
        assert result['success'] is True
        assert all(not r['success'] for r in result['results'])


# ==================== 不调用 create_stockout_core ====================

class TestBatchCreateStockoutsNoNestedTransaction:
    """验证 batch_create_stockouts 不再调用 create_stockout_core（无嵌套事务）"""

    async def test_does_not_call_create_stockout_core(self, mock_db):
        """确认不调用 create_stockout_core"""
        product = _make_product(current_stock=100)
        shipment_info = _make_shipment_info(available_quantity=50, orders=[
            {'order_id': 1, 'available': 50, 'quantity': 50}
        ])

        with patch('fastapi_app.services.stock_service.get_product_for_update', new_callable=AsyncMock, return_value=product), \
             patch('fastapi_app.services.stock_service.calculate_available_shipment_quantity', new_callable=AsyncMock, return_value=shipment_info), \
             patch('fastapi_app.services.stock_service.generate_stockout_number', new_callable=AsyncMock, return_value='SO-001'), \
             patch('fastapi_app.services.stock_service.create_stockout_core', new_callable=AsyncMock) as mock_core:

            await stock_service.batch_create_stockouts(mock_db, [_make_stockout_data(quantity=10)])

        mock_core.assert_not_awaited()

    async def test_does_not_call_db_commit(self, mock_db):
        """确认 service 层不调用 db.commit()（由 API 层统一 commit）"""
        product = _make_product(current_stock=100)
        shipment_info = _make_shipment_info(available_quantity=50, orders=[
            {'order_id': 1, 'available': 50, 'quantity': 50}
        ])

        with patch('fastapi_app.services.stock_service.get_product_for_update', new_callable=AsyncMock, return_value=product), \
             patch('fastapi_app.services.stock_service.calculate_available_shipment_quantity', new_callable=AsyncMock, return_value=shipment_info), \
             patch('fastapi_app.services.stock_service.generate_stockout_number', new_callable=AsyncMock, return_value='SO-001'):

            await stock_service.batch_create_stockouts(mock_db, [_make_stockout_data(quantity=10)])

        mock_db.commit.assert_not_awaited()

    async def test_does_not_call_db_begin_nested(self, mock_db):
        """确认不调用 db.begin_nested()（无 savepoint）"""
        product = _make_product(current_stock=100)
        shipment_info = _make_shipment_info(available_quantity=50, orders=[
            {'order_id': 1, 'available': 50, 'quantity': 50}
        ])

        with patch('fastapi_app.services.stock_service.get_product_for_update', new_callable=AsyncMock, return_value=product), \
             patch('fastapi_app.services.stock_service.calculate_available_shipment_quantity', new_callable=AsyncMock, return_value=shipment_info), \
             patch('fastapi_app.services.stock_service.generate_stockout_number', new_callable=AsyncMock, return_value='SO-001'):

            await stock_service.batch_create_stockouts(mock_db, [_make_stockout_data(quantity=10)])

        mock_db.begin_nested.assert_not_called()
