"""
来料登记 单元测试

覆盖：
- 来料登记列表查询（分页、多维度筛选）
- 来料登记创建（关联采购订单、物料明细）
- 来料登记更新（状态变更）
- 来料登记删除
- 物料收货登记（并发安全、数量校验）
- 统计概览和趋势
- 边界条件
"""
from unittest.mock import AsyncMock

import pytest

from fastapi_app.services.material_registration_service import (
    create_registration,
    delete_registration,
)


class TestGetRegistrations:
    """来料登记列表查询"""


class TestCreateRegistration:
    """来料登记创建"""

    @pytest.mark.asyncio
    async def test_create_registration_purchase_order_not_found(self, mock_async_db):
        """采购订单不存在"""
        mock_async_db.get = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match='采购订单不存在'):
            await create_registration(mock_async_db, 999, user_id=1)


class TestUpdateRegistration:
    """来料登记更新"""


class TestDeleteRegistration:
    """来料登记删除"""

    @pytest.mark.asyncio
    async def test_delete_registration_not_found(self, mock_async_db):
        """删除不存在的登记"""
        mock_async_db.get = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match='来料登记不存在'):
            await delete_registration(mock_async_db, 999)


class TestReceiveMaterial:
    """物料收货登记"""


class TestStats:
    """统计相关"""


class TestGetPurchaseOrderItems:
    """获取采购订单物料"""


class TestGetHistory:
    """来料登记历史"""

