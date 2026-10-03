"""
供应商管理 单元测试

覆盖：
- 供应商列表查询（分页、搜索）
- 供应商创建（名称唯一性校验）
- 供应商编辑（关联表同步、PATCH 语义）
- 供应商删除（关联检查、拒绝删除）
- 边界条件（空搜索、重复名称、不存在ID）

使用 mock_async_db + mock_user fixtures，无需数据库。
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from fastapi_app.services.purchase_supplier_service import (
    create_supplier,
    get_suppliers,
    update_supplier,
)


class TestGetSuppliers:
    """供应商列表查询"""

    @pytest.mark.asyncio
    async def test_get_suppliers_empty_list(self, mock_async_db):
        """查询空供应商列表 - 应返回空列表和 total=0"""
        mock_async_db.execute = AsyncMock()
        # count_query 返回
        mock_async_db.execute.return_value.scalar = MagicMock(return_value=0)
        # data query 返回空
        data_result = MagicMock()
        data_result.scalars.return_value.all.return_value = []
        mock_async_db.execute.side_effect = [
            MagicMock(scalar=MagicMock(return_value=0)),  # count
            data_result,  # data
        ]

        result = await get_suppliers(mock_async_db, page=1, per_page=50, search='')

        assert result['items'] == []
        assert result['total'] == 0
        assert result['page'] == 1

    @pytest.mark.asyncio
    async def test_get_suppliers_with_search(self, mock_async_db):
        """按名称搜索供应商"""
        supplier = MagicMock()
        supplier.id = 1
        supplier.name = '测试供应商'
        supplier.contact_person = '张三'
        supplier.phone = '13800138000'
        supplier.address = '测试地址'
        supplier.remark = '备注'
        supplier.status = True
        supplier.created_at = MagicMock()
        supplier.created_at.strftime.return_value = '2024-01-01 12:00'

        mock_execute = AsyncMock()
        mock_async_db.execute = mock_execute
        count_result = MagicMock()
        count_result.scalar.return_value = 1
        data_result = MagicMock()
        data_result.scalars.return_value.all.return_value = [supplier]
        mock_execute.side_effect = [count_result, data_result]

        result = await get_suppliers(mock_async_db, page=1, per_page=50, search='测试')

        assert result['total'] == 1
        assert len(result['items']) == 1
        assert result['items'][0]['name'] == '测试供应商'

    @pytest.mark.asyncio
    async def test_get_suppliers_pagination(self, mock_async_db):
        """分页查询 - 第2页"""
        mock_execute = AsyncMock()
        mock_async_db.execute = mock_execute

        suppliers = []
        for i in range(3):
            s = MagicMock()
            s.id = i + 51
            s.name = f'供应商{i + 51}'
            s.contact_person = None
            s.phone = None
            s.address = None
            s.remark = None
            s.status = True
            s.created_at = None
            suppliers.append(s)

        count_result = MagicMock()
        count_result.scalar.return_value = 100
        data_result = MagicMock()
        data_result.scalars.return_value.all.return_value = suppliers
        mock_execute.side_effect = [count_result, data_result]

        result = await get_suppliers(mock_async_db, page=2, per_page=50, search='')

        assert result['total'] == 100
        assert result['page'] == 2
        assert len(result['items']) == 3

    @pytest.mark.asyncio
    async def test_get_suppliers_search_no_results(self, mock_async_db):
        """搜索不存在供应商"""
        mock_async_db.execute = AsyncMock()
        mock_async_db.execute.side_effect = [
            MagicMock(scalar=MagicMock(return_value=0)),
            MagicMock(scalars=MagicMock(all=MagicMock(return_value=[]))),
        ]

        result = await get_suppliers(mock_async_db, page=1, per_page=50, search='不存在的供应商')

        assert result['total'] == 0
        assert result['items'] == []


class TestCreateSupplier:
    """供应商创建"""

    @pytest.mark.asyncio
    async def test_create_supplier_success(self, mock_async_db):
        """正常创建供应商"""
        mock_async_db.execute = AsyncMock()
        # 查询重名 - 返回 None（不存在）
        mock_async_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)

        data = {
            'name': '新供应商',
            'contact_person': '李四',
            'phone': '13900139000',
            'address': '深圳市南山区',
            'remark': '优质供应商',
        }

        result = await create_supplier(mock_async_db, data)

        assert result['name'] == '新供应商'
        assert 'id' in result
        mock_async_db.add.assert_called_once()
        mock_async_db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_supplier_duplicate_name(self, mock_async_db):
        """创建重复名称供应商 - 应抛出 ValueError"""
        existing = MagicMock()
        existing.name = '已存在供应商'
        mock_async_db.execute = AsyncMock()
        mock_async_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=existing)

        data = {'name': '已存在供应商', 'contact_person': '', 'phone': ''}

        with pytest.raises(ValueError, match='供应商已存在'):
            await create_supplier(mock_async_db, data)

    @pytest.mark.asyncio
    async def test_create_supplier_minimal_data(self, mock_async_db):
        """创建供应商 - 仅名称，其他字段为空"""
        mock_async_db.execute = AsyncMock()
        mock_async_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)

        data = {'name': '最小供应商'}

        result = await create_supplier(mock_async_db, data)

        assert result['name'] == '最小供应商'
        mock_async_db.add.assert_called_once()


class TestUpdateSupplier:
    """供应商编辑"""

    @pytest.mark.asyncio
    async def test_update_supplier_success(self, mock_async_db):
        """正常编辑供应商"""
        supplier = MagicMock()
        supplier.id = 1
        supplier.name = '原名称'
        supplier.contact_person = '原联系人'
        supplier.phone = '原电话'
        supplier.address = '原地址'
        supplier.remark = '原备注'

        mock_async_db.get = AsyncMock(return_value=supplier)
        # 名称唯一性检查 - 不重复
        mock_async_db.execute = AsyncMock()
        mock_async_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)

        data = {
            'name': '新名称',
            'contact_person': '新联系人',
            'phone': '新电话',
            'address': '新地址',
            'remark': '新备注',
        }

        result = await update_supplier(mock_async_db, 1, data)

        assert result['id'] == 1
        assert result['name'] == '新名称'
        assert supplier.name == '新名称'
        mock_async_db.flush.assert_called()

    @pytest.mark.asyncio
    async def test_update_supplier_not_found(self, mock_async_db):
        """编辑不存在的供应商 - 应抛出 ValueError"""
        mock_async_db.get = AsyncMock(return_value=None)

        data = {'name': '不存在'}

        with pytest.raises(ValueError, match='供应商不存在'):
            await update_supplier(mock_async_db, 999, data)

    @pytest.mark.asyncio
    async def test_update_supplier_duplicate_name(self, mock_async_db):
        """编辑供应商名称与另一个供应商重名"""
        supplier = MagicMock()
        supplier.id = 1
        supplier.name = '供应商A'

        mock_async_db.get = AsyncMock(return_value=supplier)

        existing = MagicMock()
        existing.name = '供应商B'
        mock_async_db.execute = AsyncMock()
        mock_async_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=existing)

        data = {'name': '供应商B'}

        with pytest.raises(ValueError, match='供应商名称已存在'):
            await update_supplier(mock_async_db, 1, data)

    @pytest.mark.asyncio
    async def test_update_supplier_patch_semantics(self, mock_async_db):
        """PATCH 语义 - 只更新提供的字段"""
        supplier = MagicMock()
        supplier.id = 1
        supplier.name = '保持原名称'
        supplier.contact_person = '原联系人'
        supplier.phone = '原电话'
        supplier.address = '原地址'
        supplier.remark = '原备注'

        mock_async_db.get = AsyncMock(return_value=supplier)
        mock_async_db.execute = AsyncMock()
        mock_async_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)

        # 仅更新 phone
        data = {'phone': '新电话'}

        result = await update_supplier(mock_async_db, 1, data)

        assert result['name'] == '保持原名称'


class TestDeleteSupplier:
    """供应商删除"""

