"""auxiliary_service.py - 单元测试

覆盖 P1-3 从 auxiliary.py endpoint 下沉的系统配置 CRUD 与编排逻辑：
- get_product_by_id
- count_inventory_logs / get_inventory_logs_page
- get_available_stockins / get_stockin_by_id
- get_supplier_by_id / supplier_has_bom_or_orders / delete_supplier
- list_countries_ordered / get_country_by_name / get_country_by_id
- create_country / delete_country
- get_system_stats

注：产品搜索已统一委托 ProductSearchService（批次 2-4），相关测试见其自身用例。
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.core.exceptions import BusinessError, ConflictError, NotFoundError
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
# create_country
# ============================================================================
class TestCreateCountry:
    @pytest.mark.asyncio
    async def test_raises_400_when_name_empty(self):
        """国家名称为空时应抛 400"""
        db = AsyncMock()
        with pytest.raises(BusinessError) as exc_info:
            await auxiliary_service.create_country(db, "")
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_raises_409_when_already_exists(self):
        """国家已存在时应抛 409"""
        db = AsyncMock()
        existing = MagicMock()
        with patch.object(auxiliary_service, 'get_country_by_name', new=AsyncMock(return_value=existing)):
            with pytest.raises(ConflictError) as exc_info:
                await auxiliary_service.create_country(db, "中国")
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_creates_new_country(self):
        """应创建新国家并返回"""
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        with patch.object(auxiliary_service, 'get_country_by_name', new=AsyncMock(return_value=None)):
            await auxiliary_service.create_country(db, "新国家")
        assert db.add.called
        assert db.flush.await_count == 1
        assert db.refresh.await_count == 1


# ============================================================================
# delete_country
# ============================================================================
class TestDeleteCountry:
    @pytest.mark.asyncio
    async def test_raises_404_when_not_found(self):
        """国家不存在时应抛 404"""
        db = AsyncMock()
        with patch.object(auxiliary_service, 'get_country_by_id', new=AsyncMock(return_value=None)):
            with pytest.raises(NotFoundError) as exc_info:
                await auxiliary_service.delete_country(db, 999)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_deletes_existing_country(self):
        """应删除已存在的国家"""
        db = AsyncMock()
        db.delete = AsyncMock()
        country = MagicMock()
        with patch.object(auxiliary_service, 'get_country_by_id', new=AsyncMock(return_value=country)):
            await auxiliary_service.delete_country(db, 1)
        assert db.delete.await_count == 1


# ============================================================================
# get_system_stats
# ============================================================================
class TestGetSystemStats:
    @pytest.mark.asyncio
    async def test_returns_stats_with_performance_data(self):
        """应返回包含 cache 与 performance 统计的字典"""
        mock_perf = MagicMock()
        mock_perf.get_stats.return_value = {"total": 100}
        mock_tracker = MagicMock()
        mock_tracker.get_stats.return_value = {"queries": 50}

        with patch('utils.performance_monitor.performance_monitor', mock_perf), \
             patch('utils.performance_monitor.query_tracker', mock_tracker):
            result = await auxiliary_service.get_system_stats()
        assert 'cache' in result
        assert 'performance' in result
        assert result['performance']['total'] == 100
        assert result['performance']['queries'] == {"queries": 50}

    @pytest.mark.asyncio
    async def test_returns_empty_stats_on_import_error(self):
        """ImportError 时应返回空统计字典"""
        with patch.dict('sys.modules', {'utils.performance_monitor': None}):
            result = await auxiliary_service.get_system_stats()
        assert result == {'cache': {}, 'performance': {}}


# ============================================================================
# list_countries_ordered
# ============================================================================
class TestListCountriesOrdered:
    @pytest.mark.asyncio
    async def test_returns_countries_list(self):
        """应返回按名称排序的国家列表"""
        c1, c2 = MagicMock(), MagicMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [c1, c2]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        result = await auxiliary_service.list_countries_ordered(db)
        assert result == [c1, c2]
