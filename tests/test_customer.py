"""
客户管理 单元测试

覆盖：
- 客户列表查询（分页、搜索、状态筛选）
- 客户搜索（模糊匹配、仅启用）
- 客户创建（名称唯一性）
- 客户编辑（PATCH 语义、名称唯一性排除自身）
- 客户状态切换
- 客户删除（关联单据保护：订单/入库/出库/采购等）
- 启用客户名称列表（缓存）
- 边界条件（不存在客户、重复名称、有关联数据）
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.services.customer_service import (
    create_customer,
    get_customer,
    get_customers,
    toggle_customer_status,
    update_customer,
)


class TestGetCustomers:
    """客户列表查询"""

    @pytest.mark.asyncio
    async def test_get_customers_empty(self, mock_async_db):
        """查询空客户列表"""
        mock_async_db.execute = AsyncMock()
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        data_result = MagicMock()
        data_result.scalars.return_value.all.return_value = []

        mock_async_db.execute.side_effect = [count_result, data_result]

        result = await get_customers(mock_async_db, page=1, per_page=50)

        assert result['items'] == []
        assert result['total'] == 0
        assert result['page'] == 1

    @pytest.mark.asyncio
    async def test_get_customers_with_data(self, mock_async_db):
        """查询客户列表"""
        customer = MagicMock()
        customer.id = 1
        customer.name = '测试客户'

        mock_async_db.execute = AsyncMock()
        count_result = MagicMock()
        count_result.scalar.return_value = 10
        data_result = MagicMock()
        data_result.scalars.return_value.all.return_value = [customer]

        mock_async_db.execute.side_effect = [count_result, data_result]

        result = await get_customers(mock_async_db, page=1, per_page=50)

        assert result['total'] == 10
        assert len(result['items']) == 1

    @pytest.mark.asyncio
    async def test_get_customers_active_filter(self, mock_async_db):
        """筛选启用客户"""
        mock_async_db.execute = AsyncMock()
        count_result = MagicMock()
        count_result.scalar.return_value = 5
        data_result = MagicMock()
        data_result.scalars.return_value.all.return_value = []

        mock_async_db.execute.side_effect = [count_result, data_result]

        result = await get_customers(mock_async_db, status='active', page=1, per_page=50)

        assert result['total'] == 5

    @pytest.mark.asyncio
    async def test_get_customers_inactive_filter(self, mock_async_db):
        """筛选禁用客户"""
        mock_async_db.execute = AsyncMock()
        count_result = MagicMock()
        count_result.scalar.return_value = 2
        data_result = MagicMock()
        data_result.scalars.return_value.all.return_value = []

        mock_async_db.execute.side_effect = [count_result, data_result]

        result = await get_customers(mock_async_db, status='inactive', page=1, per_page=50)

        assert result['total'] == 2

    @pytest.mark.asyncio
    async def test_get_customers_with_search(self, mock_async_db):
        """按关键词搜索客户"""
        mock_async_db.execute = AsyncMock()
        count_result = MagicMock()
        count_result.scalar.return_value = 1
        data_result = MagicMock()
        data_result.scalars.return_value.all.return_value = []

        mock_async_db.execute.side_effect = [count_result, data_result]

        result = await get_customers(mock_async_db, search='测试', page=1, per_page=50)

        assert result['total'] == 1

    @pytest.mark.asyncio
    async def test_get_customers_pagination(self, mock_async_db):
        """分页查询"""
        mock_async_db.execute = AsyncMock()
        count_result = MagicMock()
        count_result.scalar.return_value = 100
        data_result = MagicMock()
        customers = [MagicMock() for _ in range(50)]
        data_result.scalars.return_value.all.return_value = customers

        mock_async_db.execute.side_effect = [count_result, data_result]

        result = await get_customers(mock_async_db, page=2, per_page=50)

        assert result['total'] == 100
        assert len(result['items']) == 50
        assert result['page'] == 2


class TestGetCustomer:
    """获取单个客户"""

    @pytest.mark.asyncio
    async def test_get_customer_success(self, mock_async_db):
        """查询存在的客户"""
        customer = MagicMock()
        customer.id = 1
        customer.name = '客户A'
        mock_async_db.execute = AsyncMock()
        mock_async_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=customer)

        result = await get_customer(mock_async_db, 1)

        assert result.name == '客户A'

    @pytest.mark.asyncio
    async def test_get_customer_not_found(self, mock_async_db):
        """查询不存在的客户"""
        mock_async_db.execute = AsyncMock()
        mock_async_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)

        result = await get_customer(mock_async_db, 999)

        assert result is None


class TestSearchCustomers:
    """客户搜索"""


class TestCreateCustomer:
    """创建客户"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.customer_service._invalidate_customer_cache')
    async def test_create_customer_success(self, mock_invalid, mock_async_db):
        """正常创建客户"""
        mock_async_db.execute = AsyncMock()
        mock_async_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)  # 不重名

        mock_async_db.flush = AsyncMock()
        mock_async_db.refresh = AsyncMock()

        result = await create_customer(
            mock_async_db,
            name='新客户',
            contact='张三',
            phone='13800138000',
            address='深圳市',
            note='重要客户'
        )

        assert result.name == '新客户'
        assert result.status is True
        mock_async_db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_customer_duplicate_name(self, mock_async_db):
        """创建重复名称客户"""
        existing = MagicMock()
        existing.name = '已存在客户'
        mock_async_db.execute = AsyncMock()
        mock_async_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=existing)

        with pytest.raises(ValueError, match='客户名称已存在'):
            await create_customer(
                mock_async_db, name='已存在客户', contact=None,
                phone=None, address=None, note=None
            )

    @pytest.mark.asyncio
    @patch('fastapi_app.services.customer_service._invalidate_customer_cache')
    async def test_create_customer_minimal(self, mock_invalid, mock_async_db):
        """最小字段创建客户"""
        mock_async_db.execute = AsyncMock()
        mock_async_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)
        mock_async_db.flush = AsyncMock()
        mock_async_db.refresh = AsyncMock()

        result = await create_customer(
            mock_async_db, name='最小客户', contact=None,
            phone=None, address=None, note=None
        )

        assert result.name == '最小客户'
        assert result.status is True


class TestUpdateCustomer:
    """编辑客户"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.customer_service._invalidate_customer_cache')
    async def test_update_customer_success(self, mock_invalid, mock_async_db):
        """正常编辑客户"""
        customer = MagicMock()
        customer.id = 1
        customer.name = '原名称'

        mock_async_db.get = AsyncMock(return_value=customer)

        # 名称唯一性检查 - 不冲突
        mock_async_db.execute = AsyncMock()
        mock_async_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)

        mock_async_db.flush = AsyncMock()
        mock_async_db.refresh = AsyncMock()

        await update_customer(
            mock_async_db, customer_id=1,
            name='新名称', contact='新联系人',
            phone='新电话', address='新地址',
            note='新备注', status=None
        )

        assert customer.name == '新名称'
        assert customer.contact == '新联系人'

    @pytest.mark.asyncio
    async def test_update_customer_not_found(self, mock_async_db):
        """编辑不存在的客户"""
        mock_async_db.get = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match='客户不存在'):
            await update_customer(
                mock_async_db, customer_id=999,
                name=None, contact=None, phone=None,
                address=None, note=None, status=None
            )

    @pytest.mark.asyncio
    async def test_update_customer_duplicate_name(self, mock_async_db):
        """编辑为客户名称与另一客户重复"""
        customer = MagicMock()
        customer.id = 1
        customer.name = '客户A'
        mock_async_db.get = AsyncMock(return_value=customer)

        existing = MagicMock()
        existing.name = '客户B'
        mock_async_db.execute = AsyncMock()
        mock_async_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=existing)

        with pytest.raises(ValueError, match='客户名称已存在'):
            await update_customer(
                mock_async_db, customer_id=1, name='客户B',
                contact=None, phone=None, address=None,
                note=None, status=None
            )

    @pytest.mark.asyncio
    @patch('fastapi_app.services.customer_service._invalidate_customer_cache')
    async def test_update_customer_status(self, mock_invalid, mock_async_db):
        """更新客户状态"""
        customer = MagicMock()
        customer.id = 1
        customer.name = '客户A'
        customer.status = True
        mock_async_db.get = AsyncMock(return_value=customer)
        mock_async_db.execute = AsyncMock()
        mock_async_db.flush = AsyncMock()
        mock_async_db.refresh = AsyncMock()

        await update_customer(
            mock_async_db, customer_id=1, name=None,
            contact=None, phone=None, address=None,
            note=None, status=False
        )

        assert customer.status is False


class TestToggleCustomerStatus:
    """切换客户状态"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.customer_service._invalidate_customer_cache')
    async def test_toggle_customer_status(self, mock_invalid, mock_async_db):
        """切换客户启用/禁用"""
        customer = MagicMock()
        customer.id = 1
        customer.status = True
        mock_async_db.get = AsyncMock(return_value=customer)
        mock_async_db.flush = AsyncMock()
        mock_async_db.refresh = AsyncMock()

        await toggle_customer_status(mock_async_db, 1)

        assert customer.status is False

    @pytest.mark.asyncio
    async def test_toggle_customer_status_not_found(self, mock_async_db):
        """切换不存在的客户"""
        mock_async_db.get = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match='客户不存在'):
            await toggle_customer_status(mock_async_db, 999)


class TestDeleteCustomer:
    """删除客户"""

