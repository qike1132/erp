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

class _MockNested:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


def _make_db():
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.close = AsyncMock()
    db.flush = AsyncMock()
    db.delete = AsyncMock()
    db.refresh = AsyncMock()
    db.execute = AsyncMock()
    db.get = AsyncMock()
    db.scalar = AsyncMock(return_value=0)
    db.add = MagicMock()
    db.begin_nested = MagicMock(return_value=_MockNested())
    return db


class TestOptimisticLockUpdate:
    @pytest.mark.asyncio
    async def test_successful_update(self):
        mock_product = MagicMock(
            id=1, current_stock=100, version=1
        )

        db = _make_db()
        select_result = MagicMock()
        select_result.scalar_one_or_none.return_value = mock_product
        update_result = MagicMock()
        update_result.rowcount = 1
        db.execute = AsyncMock(side_effect=[select_result, update_result])

        product = await update_stock_with_optimistic_lock(db, 1, delta=10)
        assert product is mock_product
        db.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_raises_on_missing_product(self):
        db = _make_db()
        select_result = MagicMock()
        select_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=select_result)

        with pytest.raises(ValueError, match="产品ID 1 不存在"):
            await update_stock_with_optimistic_lock(db, 1, delta=10)

    @pytest.mark.asyncio
    async def test_raises_on_negative_stock(self):
        mock_product = MagicMock(
            id=1, current_stock=5, version=1
        )

        db = _make_db()
        select_result = MagicMock()
        select_result.scalar_one_or_none.return_value = mock_product
        db.execute = AsyncMock(return_value=select_result)

        with pytest.raises(ValueError, match="库存不足"):
            await update_stock_with_optimistic_lock(db, 1, delta=-10)

    @pytest.mark.asyncio
    async def test_retries_on_version_conflict(self):
        mock_product = MagicMock(
            id=1, current_stock=100, version=1
        )

        db = _make_db()
        select_result = MagicMock()
        select_result.scalar_one_or_none.return_value = mock_product
        mock_conflict = MagicMock(rowcount=0)
        mock_success = MagicMock(rowcount=1)
        # UPDATE 影响 0 行后，入口会按 (id, version == old_version) 重读一行以区分
        # 「库存不足」与「版本冲突」(_classify_update_miss)；此处重读返回 version 已变
        # （2 != 1）的产品 ⇒ 判定为版本冲突，维持既有 savepoint + 重试路径。
        classify_result = MagicMock()
        classify_result.scalar_one_or_none.return_value = MagicMock(
            id=1, current_stock=100, version=2
        )
        db.execute = AsyncMock(side_effect=[
            select_result, mock_conflict, classify_result, select_result, mock_success,
        ])

        product = await update_stock_with_optimistic_lock(db, 1, delta=5, retries=3)
        assert product is mock_product
        # 2 轮 savepoint，每轮 SELECT + UPDATE，冲突后各追加 1 次重读：共 5 次 execute
        assert db.execute.await_count == 5
        assert classify_result.scalar_one_or_none.call_count == 1
        assert db.begin_nested.call_count == 2

    @pytest.mark.asyncio
    async def test_raises_after_max_retries(self):
        mock_product = MagicMock(
            id=1, current_stock=100, version=1
        )

        db = _make_db()
        select_result = MagicMock()
        select_result.scalar_one_or_none.return_value = mock_product
        mock_conflict = MagicMock(rowcount=0)
        # 同 test_retries_on_version_conflict：每次冲突后的重读返回 version 已变的产品
        classify_result = MagicMock()
        classify_result.scalar_one_or_none.return_value = MagicMock(
            id=1, current_stock=100, version=2
        )
        db.execute = AsyncMock(side_effect=[
            select_result, mock_conflict, classify_result,
            select_result, mock_conflict, classify_result,
        ])

        with pytest.raises(StockConcurrentError, match=r"重试.*次后仍失败"):
            await update_stock_with_optimistic_lock(db, 1, delta=5, retries=2)
        # retries=2 ⇒ 2 轮 savepoint，各自 SELECT + UPDATE + 冲突后重读：共 6 次 execute
        assert db.execute.await_count == 6
        assert classify_result.scalar_one_or_none.call_count == 2
        assert db.begin_nested.call_count == 2


# ============================================================
# StockConcurrentError
# ============================================================

class TestStockConcurrentError:
    def test_is_exception(self):
        assert issubclass(StockConcurrentError, Exception)

    def test_max_retry_constant(self):
        assert MAX_RETRY == 3
