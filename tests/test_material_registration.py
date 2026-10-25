"""
来料登记 单元测试

覆盖：
- 来料登记创建（关联采购订单）
- 来料登记删除

M-H（2026-10-25 复审）：原文件挂了 6 个零测试方法的空类（列表查询/更新/收货/
统计/订单物料/历史），只制造「已测」假象——已删除；这些域的行为覆盖在
fastapi_app/tests/test_material_registration.py（computed_status 三分支真断言等）。
"""
from unittest.mock import AsyncMock

import pytest

from fastapi_app.services.material_registration_service import (
    create_registration,
    delete_registration,
)


class TestCreateRegistration:
    """来料登记创建"""

    @pytest.mark.asyncio
    async def test_create_registration_purchase_order_not_found(self, mock_async_db):
        """采购订单不存在"""
        mock_async_db.get = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match='采购订单不存在'):
            await create_registration(mock_async_db, 999, user_id=1)


class TestDeleteRegistration:
    """来料登记删除"""

    @pytest.mark.asyncio
    async def test_delete_registration_not_found(self, mock_async_db):
        """删除不存在的登记"""
        mock_async_db.get = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match='来料登记不存在'):
            await delete_registration(mock_async_db, 999)
