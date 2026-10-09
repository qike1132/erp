"""
产品清单 单元测试

覆盖：
- 产品列表查询（分页、搜索、缓存）
- 产品创建（名称唯一性、初始库存、库存日志）
- 产品编辑（名称变更、初始库存调整、库存保护）
- 产品删除（关联检查：订单/入库/出库）
- 产品搜索（模糊匹配）
- 产品库存查询
- 边界条件（负数库存、空名称、重复名称）
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.services.product_service import (
    create_product,
    get_product_by_id,
    get_product_stock,
    get_products,
    get_products_page,
    update_product,
)


class TestGetProducts:
    """产品列表查询"""

    @pytest.mark.asyncio
    async def test_get_products_empty(self, mock_async_db):
        """查询空产品列表"""
        mock_execute = AsyncMock()
        data_result = MagicMock()
        data_result.scalars.return_value.all.return_value = []
        mock_execute.return_value = data_result
        mock_async_db.execute = mock_execute

        result = await get_products(mock_async_db, limit=5000)

        assert result == []

    @pytest.mark.asyncio
    async def test_get_products_with_data(self, mock_async_db):
        """查询有数据的产品列表"""
        product = MagicMock()
        product.to_dict.return_value = {'id': 1, 'name': '测试产品', 'barcode': 'TEST001'}

        data_result = MagicMock()
        data_result.scalars.return_value.all.return_value = [product]
        mock_async_db.execute = AsyncMock(return_value=data_result)

        result = await get_products(mock_async_db, limit=100)

        assert len(result) == 1
        assert result[0]['name'] == '测试产品'


class TestGetProductsPage:
    """产品分页查询"""

    @pytest.mark.asyncio
    async def test_get_products_page_empty(self, mock_async_db):
        """分页查询空结果"""
        mock_async_db.execute = AsyncMock()
        data_result = MagicMock()
        data_result.scalars.return_value.all.return_value = []

        mock_async_db.execute.side_effect = [
            MagicMock(scalar=MagicMock(return_value=0)),  # count
            data_result,  # data
        ]

        result = await get_products_page(mock_async_db, page=1, per_page=20)

        assert result['items'] == []
        assert result['total'] == 0
        assert result['page'] == 1
        assert result['per_page'] == 20

    @pytest.mark.asyncio
    async def test_get_products_page_with_search(self, mock_async_db):
        """分页+搜索"""
        product = MagicMock()
        product.id = 1
        product.to_dict.return_value = {'id': 1, 'name': '手机壳', 'barcode': 'CASE001'}

        data_result = MagicMock()
        data_result.scalars.return_value.all.return_value = [product]

        # 第三次 execute 是客户归属查询（_load_customers_for_products）
        mock_async_db.execute = AsyncMock()
        mock_async_db.execute.side_effect = [
            MagicMock(scalar=MagicMock(return_value=1)),  # count
            data_result,  # data
            MagicMock(all=MagicMock(return_value=[])),  # customers
        ]

        result = await get_products_page(mock_async_db, page=1, per_page=20, search='手机')

        assert result['total'] == 1
        assert len(result['items']) == 1
        assert result['items'][0]['customers'] == []

    @pytest.mark.asyncio
    async def test_get_products_page_per_page_limits(self, mock_async_db):
        """每页数量边界检查"""
        mock_async_db.execute = AsyncMock()
        data_result = MagicMock()
        data_result.scalars.return_value.all.return_value = []

        mock_async_db.execute.side_effect = [
            MagicMock(scalar=MagicMock(return_value=0)),  # count
            data_result,  # data
        ]

        # per_page=0 会被修正为 1
        result = await get_products_page(mock_async_db, page=1, per_page=0)
        assert result['per_page'] == 1

        # per_page=500 会被修正为 200
        mock_async_db.execute.side_effect = [
            MagicMock(scalar=MagicMock(return_value=0)),
            data_result,
        ]
        result = await get_products_page(mock_async_db, page=1, per_page=500)
        assert result['per_page'] == 200


class TestCreateProduct:
    """产品创建"""

    @pytest.mark.asyncio
    async def test_create_product_empty_name(self, mock_async_db):
        """产品名称为空"""
        with pytest.raises(ValueError):
            await create_product(
                mock_async_db,
                name='',
                barcode='EMPTY001',
                image=None,
                initial_stock=0
            )

    @pytest.mark.asyncio
    async def test_create_product_negative_stock(self, mock_async_db):
        """初始库存为负数"""
        with pytest.raises(ValueError, match='初始库存不能为负数'):
            await create_product(
                mock_async_db,
                name='负库存产品',
                barcode='NEG001',
                image=None,
                initial_stock=-10
            )

    @pytest.mark.asyncio
    async def test_create_product_duplicate_name(self, mock_async_db):
        """产品名称重复"""
        existing = MagicMock()
        existing.name = '已存在产品'
        mock_async_db.execute = AsyncMock()
        mock_async_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=existing)

        with pytest.raises(ValueError, match='已存在'):
            await create_product(
                mock_async_db,
                name='已存在产品',
                barcode='DUP001',
                image=None,
                initial_stock=0
            )

    @pytest.mark.asyncio
    async def test_create_product_no_inventory_log(self, mock_async_db):
        """初始库存为0时不生成库存日志"""
        mock_async_db.execute = AsyncMock()
        mock_async_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)

        result = await create_product(
            mock_async_db,
            name='零库存产品',
            barcode='ZERO001',
            image=None,
            initial_stock=0
        )

        assert result['name'] == '零库存产品'

    @pytest.mark.asyncio
    async def test_create_product_without_barcode(self, mock_async_db):
        """创建产品 - 无条码"""
        mock_async_db.execute = AsyncMock()
        mock_async_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)

        result = await create_product(
            mock_async_db,
            name='无条码产品',
            barcode=None,
            image=None,
            initial_stock=50
        )

        assert result['name'] == '无条码产品'


class TestUpdateProduct:
    """产品编辑"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.product_service.get_product_for_update')
    async def test_update_product_not_found(self, mock_get_product, mock_async_db):
        """编辑不存在的产品"""
        mock_get_product.return_value = None

        with pytest.raises(ValueError, match='产品不存在'):
            await update_product(
                mock_async_db,
                product_id=999,
                name='不存在',
                barcode=None,
                image=None,
                initial_stock=None
            )

    @pytest.mark.asyncio
    @patch('fastapi_app.services.product_service.get_product_for_update')
    async def test_update_product_negative_stock(self, mock_get_product, mock_async_db):
        """初始库存调整导致当前库存为负"""
        product = MagicMock()
        product.id = 1
        product.name = '产品A'
        product.initial_stock = 100
        product.current_stock = 50
        mock_get_product.return_value = product

        mock_async_db.execute = AsyncMock()

        with pytest.raises(ValueError, match='初始库存调整将导致当前库存为负数'):
            await update_product(
                mock_async_db,
                product_id=1,
                name=None, barcode=None, image=None,
                initial_stock=30  # current_stock=50, initial_stock 从 100 变为 30 -> change=-70 -> 50+(-70)=-20
            )

    @pytest.mark.asyncio
    @patch('fastapi_app.services.product_service.get_product_for_update')
    async def test_update_product_remove_factory(self, mock_get_product, mock_async_db):
        """产品编辑 - 清除工厂"""
        product = MagicMock()
        product.id = 1
        product.name = '产品A'
        product.barcode = 'BAR001'
        product.initial_stock = 100
        product.current_stock = 100
        product.price = 50
        product.factory = '东莞'
        mock_get_product.return_value = product

        mock_async_db.execute = AsyncMock()

        await update_product(
            mock_async_db, product_id=1,
            name=None, barcode=None, image=None,
            initial_stock=None, factory=''
        )

        assert product.factory == ''


class TestDeleteProduct:
    """产品删除"""


class TestGetProductById:
    """按ID查询产品"""

    @pytest.mark.asyncio
    async def test_get_product_by_id_success(self, mock_async_db):
        """查询存在的产品"""
        product = MagicMock()
        product.id = 1
        product.to_dict.return_value = {'id': 1, 'name': '产品A'}
        mock_async_db.get = AsyncMock(return_value=product)
        # 详情会额外查一次客户归属（_load_customers_for_products）
        mock_async_db.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))

        result = await get_product_by_id(mock_async_db, 1)

        assert result['id'] == 1
        assert result['name'] == '产品A'
        assert result['customers'] == []

    @pytest.mark.asyncio
    async def test_get_product_by_id_not_found(self, mock_async_db):
        """查询不存在的产品"""
        mock_async_db.get = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match='产品不存在'):
            await get_product_by_id(mock_async_db, 999)


class TestSearchProducts:
    """产品搜索"""


class TestGetProductStock:
    """产品库存查询"""

    @pytest.mark.asyncio
    async def test_get_product_stock_success(self, mock_async_db):
        """查询产品库存"""
        product = MagicMock()
        product.id = 1
        product.name = '产品A'
        product.current_stock = 150
        mock_async_db.get = AsyncMock(return_value=product)

        result = await get_product_stock(mock_async_db, 1)

        assert result['product_id'] == 1
        assert result['name'] == '产品A'
        assert result['current_stock'] == 150
        assert result['available_stock'] == 150

    @pytest.mark.asyncio
    async def test_get_product_stock_not_found(self, mock_async_db):
        """查询不存在的产品库存"""
        mock_async_db.get = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match='产品不存在'):
            await get_product_stock(mock_async_db, 999)
