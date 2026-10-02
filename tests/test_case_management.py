"""皮套管理 单元测试（统一流水 + SKU 主档）

覆盖：辅助函数、流水方向/数量校验、SKU 创建必填校验。
"""
from unittest.mock import AsyncMock

import pytest

from fastapi_app.core.exceptions import BusinessError
from fastapi_app.services.case_service import (
    _normalize_pagination,
    _parse_date,
)


class TestHelpers:
    """辅助函数测试"""

    def test_parse_date_valid(self):
        """合法日期"""
        result = _parse_date('2024-06-15')
        assert result is not None

    def test_parse_date_invalid(self):
        """非法日期格式"""
        with pytest.raises(BusinessError):
            _parse_date('2024/06/15')

    def test_normalize_pagination_valid(self):
        page, per_page = _normalize_pagination(2, 30, 100)
        assert page == 2
        assert per_page == 30

    def test_normalize_pagination_page_zero(self):
        page, _per_page = _normalize_pagination(0, 20, 100)
        assert page == 1

    def test_normalize_pagination_page_negative(self):
        page, _per_page = _normalize_pagination(-5, 20, 100)
        assert page == 1

    def test_normalize_pagination_exceed_max(self):
        _page, per_page = _normalize_pagination(1, 300, 100)
        assert per_page == 100

    def test_normalize_pagination_per_page_zero(self):
        _page, per_page = _normalize_pagination(1, 0, 100)
        assert per_page == 1


class TestMovementValidation:
    """流水方向 / 数量校验（在任何 DB 访问前抛错）"""

    @pytest.mark.asyncio
    async def test_invalid_direction(self):
        from fastapi_app.services.case_service import create_movement
        with pytest.raises(ValueError, match="方向必须是 in 或 out"):
            await create_movement(AsyncMock(), 1, 'sideways', 5, '2024-06-15')

    @pytest.mark.asyncio
    async def test_zero_quantity(self):
        from fastapi_app.services.case_service import create_movement
        with pytest.raises((BusinessError, ValueError)):
            await create_movement(AsyncMock(), 1, 'in', 0, '2024-06-15')


class TestItemCreate:
    """SKU 创建必填校验"""

    @pytest.mark.asyncio
    async def test_requires_name_or_product(self):
        from fastapi_app.services.case_service import create_case_item
        with pytest.raises(ValueError, match="不能为空"):
            await create_case_item(AsyncMock())
