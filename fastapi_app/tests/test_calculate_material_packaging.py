"""calculate_material packaging 类别专项单元测试"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from fastapi_app.services.purchase_product_service import aggregate_materials, calculate_material


class TestCalculateMaterialPackaging:
    """验证 calculate_material 正确处理 packaging 类别物料"""

    @pytest.mark.asyncio
    async def test_result_dict_contains_packaging_key(self):
        """result 字典初始化必须包含 packaging 键"""
        # 空订单列表应返回包含 packaging 的字典
        result = await calculate_material(MagicMock(), [])
        assert 'packaging' in result, "result 字典缺少 packaging 键"
        assert isinstance(result['packaging'], list)

    @pytest.mark.asyncio
    async def test_packaging_material_not_silently_dropped(self):
        """packaging 类别物料不应被静默丢弃"""
        # 构造 mock product，其 get_all_materials 返回包含 packaging 的物料
        mock_product = MagicMock()
        mock_product.id = 1
        mock_product.has_bom.return_value = True
        mock_product.get_all_materials.return_value = [
            {
                'category': 'fabric',
                'material_name': '面料A',
                'unit_usage': 2.5,
                'unit': '码',
                'supplier_name': '供应商1',
                'specification': '规格1',
                'material_code': 'F001',
            },
            {
                'category': 'packaging',
                'material_name': '包装盒',
                'unit_usage': 1.0,
                'unit': '个',
                'supplier_name': '包装供应商',
                'specification': '30x20x10',
                'material_code': 'P001',
            },
            {
                'category': 'accessory',
                'material_name': '拉链',
                'unit_usage': 2.0,
                'unit': '条',
                'supplier_name': '辅料供应商',
                'specification': '20cm',
                'material_code': 'A001',
            },
        ]

        # mock db.execute 返回包含 mock_product 的结果
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.unique.return_value.all.return_value = [mock_product]
        mock_result.scalars.return_value = mock_scalars
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        orders_data = [{'product_id': 1, 'quantity': 100}]

        result = await calculate_material(mock_db, orders_data)

        # 验证所有类别都有结果
        assert len(result['fabric']) > 0, "fabric 类别无结果"
        assert len(result['packaging']) > 0, "packaging 类别无结果 — 物料被静默丢弃!"
        assert len(result['accessory']) > 0, "accessory 类别无结果"

        # 验证 packaging 物料的具体值
        pkg_item = result['packaging'][0]
        assert pkg_item['material_name'] == '包装盒'
        assert pkg_item['total_quantity'] == 100.0  # 1.0 * 100
        assert pkg_item['unit'] == '个'
        assert pkg_item['supplier_name'] == '包装供应商'
        assert pkg_item['material_code'] == 'P001'

    @pytest.mark.asyncio
    async def test_packaging_quantity_calculation_correct(self):
        """packaging 物料数量计算正确（unit_usage × order_quantity）"""
        mock_product = MagicMock()
        mock_product.id = 1
        mock_product.has_bom.return_value = True
        mock_product.get_all_materials.return_value = [
            {
                'category': 'packaging',
                'material_name': '纸箱',
                'unit_usage': 0.5,
                'unit': '箱',
                'supplier_name': '',
                'specification': '',
                'material_code': '',
            },
        ]

        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.unique.return_value.all.return_value = [mock_product]
        mock_result.scalars.return_value = mock_scalars
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        orders_data = [{'product_id': 1, 'quantity': 200}]

        result = await calculate_material(mock_db, orders_data)

        assert len(result['packaging']) == 1
        assert result['packaging'][0]['total_quantity'] == 100.0  # 0.5 * 200

    @pytest.mark.asyncio
    async def test_multiple_packaging_materials_aggregated(self):
        """多种 packaging 物料分别聚合"""
        mock_product = MagicMock()
        mock_product.id = 1
        mock_product.has_bom.return_value = True
        mock_product.get_all_materials.return_value = [
            {
                'category': 'packaging',
                'material_name': '纸箱',
                'unit_usage': 1.0,
                'unit': '箱',
                'supplier_name': 'A',
                'specification': '大',
                'material_code': 'P01',
            },
            {
                'category': 'packaging',
                'material_name': '气泡膜',
                'unit_usage': 2.0,
                'unit': '米',
                'supplier_name': 'B',
                'specification': '50cm',
                'material_code': 'P02',
            },
        ]

        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.unique.return_value.all.return_value = [mock_product]
        mock_result.scalars.return_value = mock_scalars
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        orders_data = [{'product_id': 1, 'quantity': 50}]

        result = await calculate_material(mock_db, orders_data)

        assert len(result['packaging']) == 2
        names = {item['material_name'] for item in result['packaging']}
        assert names == {'纸箱', '气泡膜'}

    @pytest.mark.asyncio
    async def test_same_name_different_supplier_not_merged(self):
        """同名物料但供应商/规格不同时不应被错误合并"""
        mock_product = MagicMock()
        mock_product.id = 1
        mock_product.has_bom.return_value = True
        mock_product.get_all_materials.return_value = [
            {
                'category': 'fabric',
                'material_name': '面料A',
                'unit_usage': 2.0,
                'unit': '码',
                'supplier_name': '供应商甲',
                'specification': '厚款',
                'material_code': 'F01',
            },
            {
                'category': 'fabric',
                'material_name': '面料A',
                'unit_usage': 2.0,
                'unit': '码',
                'supplier_name': '供应商乙',
                'specification': '薄款',
                'material_code': 'F02',
            },
        ]

        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.unique.return_value.all.return_value = [mock_product]
        mock_result.scalars.return_value = mock_scalars
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        orders_data = [{'product_id': 1, 'quantity': 10}]

        result = await calculate_material(mock_db, orders_data)

        # 两个供应商应分别保留两行，而非合并成一行
        assert len(result['fabric']) == 2, "同名不同供应商的物料被错误合并"
        suppliers = {item['supplier_name'] for item in result['fabric']}
        assert suppliers == {'供应商甲', '供应商乙'}
        for item in result['fabric']:
            assert item['total_quantity'] == 20.0  # 2.0 * 10


class TestAggregateMaterialsKeyCollision:
    """验证聚合 key 策略，覆盖分隔符碰撞与同名不同规格场景"""

    def _make_product(self, materials):
        p = MagicMock()
        p.id = 1
        p.has_bom.return_value = True
        p.get_all_materials.return_value = materials
        return p

    def test_separator_in_name_does_not_collapse_rows(self):
        """物料名含 ':' 时不应与分隔符产生键冲突（回归测试 R2）"""
        product = self._make_product([
            {
                'category': 'fabric',
                'material_name': 'a:b',  # 名字含分隔符
                'unit_usage': 1.0,
                'unit': '码',
                'supplier_name': '',
                'specification': 'spec1',
                'material_code': 'X1',
            },
            {
                'category': 'fabric',
                'material_name': 'a',
                'unit_usage': 1.0,
                'unit': '码',
                'supplier_name': 'b',  # 与上一条的 'a:b' 用 ':' 拼接会冲突
                'specification': 'spec1',
                'material_code': 'X2',
            },
        ])
        result = aggregate_materials([{'product_id': 1, 'quantity': 5}], {1: product})

        # 两条物料必须分别保留，不可因 ':' 分隔符碰撞而合并
        assert len(result['fabric']) == 2, "聚合 key 因分隔符 ':' 产生碰撞"
        codes = {row['material_code'] for row in result['fabric']}
        assert codes == {'X1', 'X2'}
        for row in result['fabric']:
            assert row['total_quantity'] == 5.0

    def test_same_name_different_specification_not_merged(self):
        """同名同供应商但规格不同时不应合并"""
        product = self._make_product([
            {
                'category': 'accessory', 'material_name': '纽扣',
                'unit_usage': 4.0, 'unit': '颗',
                'supplier_name': '供应商甲', 'specification': '大号',
                'material_code': 'B1',
            },
            {
                'category': 'accessory', 'material_name': '纽扣',
                'unit_usage': 4.0, 'unit': '颗',
                'supplier_name': '供应商甲', 'specification': '小号',
                'material_code': 'B2',
            },
        ])
        result = aggregate_materials([{'product_id': 1, 'quantity': 10}], {1: product})

        assert len(result['accessory']) == 2
        specs = {row['specification'] for row in result['accessory']}
        assert specs == {'大号', '小号'}
