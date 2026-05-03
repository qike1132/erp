"""
stock_concurrency 模块单元测试

覆盖：get_product_for_update、update_stock_with_optimistic_lock、StockConcurrentError
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from fastapi_app.shared.stock_concurrency import (
    MAX_RETRY,
    StockConcurrentError,
    get_product_for_update,
    update_stock_with_optimistic_lock,
)

# ============================================================
# get_product_for_update
# ============================================================

class TestGetProductForUpdate:
    @pytest.mark.asyncio
    async def test_returns_product(self):
        mock_product = MagicMock(id=1, name="测试产品", current_stock=100)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_product

        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)

        product = await get_product_for_update(db, 1)
        assert product.id == 1
        assert product.current_stock == 100

    @pytest.mark.asyncio
    async def test_raises_on_missing_product(self):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValueError, match="产品ID 999 不存在"):
            await get_product_for_update(db, 999)


# ============================================================
# update_stock_with_optimistic_lock
# ============================================================

class TestOptimisticLockUpdate:
    @pytest.mark.asyncio
    async def test_successful_update(self):
        mock_product = MagicMock(
            id=1, current_stock=100, version=1
        )

        db = AsyncMock()
        db.get = AsyncMock(return_value=mock_product)

        mock_exec_result = MagicMock()
        mock_exec_result.rowcount = 1
        db.execute = AsyncMock(return_value=mock_exec_result)
        db.refresh = AsyncMock()

        product = await update_stock_with_optimistic_lock(db, 1, delta=10)
        assert product is mock_product
        db.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_raises_on_missing_product(self):
        db = AsyncMock()
        db.get = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="产品ID 1 不存在"):
            await update_stock_with_optimistic_lock(db, 1, delta=10)

    @pytest.mark.asyncio
    async def test_raises_on_negative_stock(self):
        mock_product = MagicMock(
            id=1, current_stock=5, version=1
        )
        db = AsyncMock()
        db.get = AsyncMock(return_value=mock_product)

        with pytest.raises(ValueError, match="库存不足"):
            await update_stock_with_optimistic_lock(db, 1, delta=-10)

    @pytest.mark.asyncio
    async def test_retries_on_version_conflict(self):
        mock_product = MagicMock(
            id=1, current_stock=100, version=1
        )

        db = AsyncMock()
        db.get = AsyncMock(return_value=mock_product)
        db.rollback = AsyncMock()
        db.refresh = AsyncMock()

        # First 2 calls conflict (rowcount=0), third succeeds
        mock_conflict = MagicMock(rowcount=0)
        mock_success = MagicMock(rowcount=1)
        db.execute = AsyncMock(side_effect=[mock_conflict, mock_conflict, mock_success])

        product = await update_stock_with_optimistic_lock(db, 1, delta=5, retries=3)
        assert product is mock_product
        assert db.rollback.await_count == 2

    @pytest.mark.asyncio
    async def test_raises_after_max_retries(self):
        mock_product = MagicMock(
            id=1, current_stock=100, version=1
        )

        db = AsyncMock()
        db.get = AsyncMock(return_value=mock_product)
        db.rollback = AsyncMock()

        mock_conflict = MagicMock(rowcount=0)
        db.execute = AsyncMock(return_value=mock_conflict)

        with pytest.raises(StockConcurrentError, match="重试.*次后仍失败"):
            await update_stock_with_optimistic_lock(db, 1, delta=5, retries=2)


# ============================================================
# StockConcurrentError
# ============================================================

class TestStockConcurrentError:
    def test_is_exception(self):
        assert issubclass(StockConcurrentError, Exception)

    def test_max_retry_constant(self):
        assert MAX_RETRY == 3
