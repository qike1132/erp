"""auxiliary_service.py - 单元测试

覆盖 P1-3 从 auxiliary.py endpoint 下沉的系统配置 CRUD 与编排逻辑：
- get_product_by_id
- count_inventory_logs / get_inventory_logs_page
- get_available_stockins / get_stockin_by_id
- get_supplier_by_id / supplier_has_bom_or_orders / delete_supplier
- get_system_stats

注：产品搜索已统一委托 ProductSearchService（批次 2-4），相关测试见其自身用例。
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.core.exceptions import BusinessError, NotFoundError
from fastapi_app.services import auxiliary_service


# ============================================================================
# get_product_by_id
# ============================================================================
class TestGetProductById:
    @pytest.mark.asyncio
    async def test_returns_product(self):
        """应通过 db.get 返回产品"""
        product = MagicMock()
        db = AsyncMock()
        db.get = AsyncMock(return_value=product)

        result = await auxiliary_service.get_product_by_id(db, 1)
        assert result is product

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        """产品不存在时应返回 None"""
        db = AsyncMock()
        db.get = AsyncMock(return_value=None)

        result = await auxiliary_service.get_product_by_id(db, 999)
        assert result is None


# ============================================================================
# count_inventory_logs
# ============================================================================
class TestCountInventoryLogs:
    @pytest.mark.asyncio
    async def test_returns_count(self):
        """应返回库存日志总数"""
        result_mock = MagicMock()
        result_mock.scalar.return_value = 42
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        count = await auxiliary_service.count_inventory_logs(db, 1)
        assert count == 42

    @pytest.mark.asyncio
    async def test_returns_zero_when_none(self):
        """scalar 为 None 时应返回 0"""
        result_mock = MagicMock()
        result_mock.scalar.return_value = None
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        count = await auxiliary_service.count_inventory_logs(db, 1)
        assert count == 0


# ============================================================================
# get_inventory_logs_page
# ============================================================================
class TestGetInventoryLogsPage:
    @pytest.mark.asyncio
    async def test_returns_paginated_logs(self):
        """应返回分页后的日志列表"""
        log1, log2 = MagicMock(), MagicMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [log1, log2]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        logs = await auxiliary_service.get_inventory_logs_page(db, 1, page=1, per_page=20)
        assert logs == [log1, log2]


# ============================================================================
# get_available_stockins
# ============================================================================
class TestGetAvailableStockins:
    @pytest.mark.asyncio
    async def test_with_product_id_and_customer(self):
        """同时提供 product_id 和 customer 时应返回筛选结果"""
        si1 = MagicMock()
        result_mock = MagicMock()
        result_mock.unique.return_value.scalars.return_value.all.return_value = [si1]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        result = await auxiliary_service.get_available_stockins(db, 1, "客户A", limit=50)
        assert result == [si1]

    @pytest.mark.asyncio
    async def test_without_product_id(self):
        """product_id 为 None 时不应添加 product_id 筛选"""
        result_mock = MagicMock()
        result_mock.unique.return_value.scalars.return_value.all.return_value = []
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        result = await auxiliary_service.get_available_stockins(db, None, "客户A", limit=10)
        assert result == []


# ============================================================================
# get_stockin_by_id
# ============================================================================
class TestGetStockinById:
    @pytest.mark.asyncio
    async def test_returns_stockin(self):
        si = MagicMock()
        db = AsyncMock()
        db.get = AsyncMock(return_value=si)
        assert await auxiliary_service.get_stockin_by_id(db, 1) is si

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        db = AsyncMock()
        db.get = AsyncMock(return_value=None)
        assert await auxiliary_service.get_stockin_by_id(db, 999) is None


# ============================================================================
# supplier_has_bom_or_orders
# ============================================================================
class TestSupplierHasBomOrOrders:
    @pytest.mark.asyncio
    async def test_returns_true_when_has_bom(self):
        """有 BOM 关联时应返回 True"""
        db = AsyncMock()
        # 4 次查询：material / fabric / accessory / order
        has_material = MagicMock()
        has_material.scalar.return_value = 1
        empty = MagicMock()
        empty.scalar.return_value = None
        db.execute = AsyncMock(side_effect=[has_material, empty, empty, empty])

        result = await auxiliary_service.supplier_has_bom_or_orders(db, 1)
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_true_when_has_orders(self):
        """有采购订单关联时应返回 True"""
        db = AsyncMock()
        empty = MagicMock()
        empty.scalar.return_value = None
        has_order = MagicMock()
        has_order.scalar.return_value = 5
        db.execute = AsyncMock(side_effect=[empty, empty, empty, has_order])

        result = await auxiliary_service.supplier_has_bom_or_orders(db, 1)
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_no_associations(self):
        """无任何关联时应返回 False"""
        db = AsyncMock()
        empty = MagicMock()
        empty.scalar.return_value = None
        db.execute = AsyncMock(side_effect=[empty, empty, empty, empty])

        result = await auxiliary_service.supplier_has_bom_or_orders(db, 1)
        assert result is False


# ============================================================================
# delete_supplier
# ============================================================================
class TestDeleteSupplier:
    @pytest.mark.asyncio
    async def test_raises_404_when_supplier_not_found(self):
        """供应商不存在时应抛 404"""
        db = AsyncMock()
        with patch.object(auxiliary_service, 'get_supplier_by_id', new=AsyncMock(return_value=None)):
            with pytest.raises(NotFoundError) as exc_info:
                await auxiliary_service.delete_supplier(db, 999)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_raises_400_when_has_associations(self):
        """存在 BOM/订单关联时应抛 400"""
        db = AsyncMock()
        supplier = MagicMock()
        with patch.object(auxiliary_service, 'get_supplier_by_id', new=AsyncMock(return_value=supplier)), \
             patch.object(auxiliary_service, 'supplier_has_bom_or_orders', new=AsyncMock(return_value=True)):
            with pytest.raises(BusinessError) as exc_info:
                await auxiliary_service.delete_supplier(db, 1)
        assert exc_info.value.status_code == 400


# ============================================================================
# get_system_stats
# ============================================================================
class TestGetSystemStats:
    @pytest.mark.asyncio
    async def test_returns_real_cache_stats_and_not_instrumented_performance(self):
        """cache 必须来自真实 redis_cache；无埋点的 performance 明确标 not_instrumented。"""
        from utils.redis_cache import redis_cache

        real_stats = {'backend': 'redis', 'connected': True, 'keyspace_hits': 5}

        with patch.object(redis_cache, 'get_stats', new=AsyncMock(return_value=real_stats)):
            result = await auxiliary_service.get_system_stats()

        assert result['cache'] == real_stats
        assert result['performance']['status'] == 'not_instrumented'
        assert result['performance']['queries']['status'] == 'not_instrumented'
        # 不再返回误导性的全 0 假字段
        assert 'total_requests' not in result['performance']
        assert 'errors' not in result['performance']

    @pytest.mark.asyncio
    async def test_cache_stats_failure_is_reported_not_raised(self):
        """缓存探测失败时降级为 unavailable，端点不得 500。"""
        from utils.redis_cache import redis_cache

        with patch.object(redis_cache, 'get_stats', new=AsyncMock(side_effect=RuntimeError('redis down'))):
            result = await auxiliary_service.get_system_stats()

        assert result['cache']['status'] == 'unavailable'
        assert 'redis down' in result['cache']['error']
        assert result['performance']['status'] == 'not_instrumented'
