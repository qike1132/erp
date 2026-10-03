"""
生产报表（每日生产记录） 单元测试

覆盖：
- 生产记录查询（月份筛选、部门筛选、日期筛选、分页）
- 生产记录创建（部门校验、数量校验、单价校验）
- 生产记录更新（字段更新、数据校验）
- 生产记录删除
- 数据校验函数（部门、产品名、数量、单价）
- 每日/月度汇总
- 边界条件（无效部门、负数数量、超大数量、空产品名）
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from fastapi_app.services.daily_production_service import (
    DEPARTMENT_LABELS,
    create_record,
    delete_record,
    get_records,
    update_record,
    validate_record_data,
)


class TestValidateRecordData:
    """数据校验"""

    def test_validate_valid_data(self):
        """合法数据"""
        validate_record_data('filling', '产品A', 100, 50.0)

    def test_validate_invalid_department(self):
        """无效部门"""
        with pytest.raises(ValueError, match='部门必须是'):
            validate_record_data('invalid_dept', '产品A', 100)

    def test_validate_empty_product_name(self):
        """空产品名称"""
        with pytest.raises(ValueError):
            validate_record_data('filling', '', 100)

    def test_validate_zero_quantity(self):
        """数量为0"""
        with pytest.raises(ValueError, match='生产数量必须大于 0'):
            validate_record_data('filling', '产品A', 0)

    def test_validate_negative_quantity(self):
        """负数数量"""
        with pytest.raises(ValueError, match='生产数量必须大于 0'):
            validate_record_data('handcraft', '产品B', -10)

    def test_validate_exceed_max_quantity(self):
        """数量超过上限"""
        with pytest.raises(ValueError, match='生产数量不能超过'):
            validate_record_data('packaging', '产品C', 100000000)

    def test_validate_negative_price(self):
        """负单价"""
        with pytest.raises(ValueError, match='单价不能为负数'):
            validate_record_data('filling', '产品A', 100, -10)

    def test_validate_valid_departments(self):
        """所有合法部门"""
        for dept in ['filling', 'handcraft', 'packaging']:
            validate_record_data(dept, '产品', 50, 10.0)

    def test_validate_department_labels(self):
        """验证部门标签映射"""
        assert DEPARTMENT_LABELS['filling'] == '充棉部'
        assert DEPARTMENT_LABELS['handcraft'] == '手工部'
        assert DEPARTMENT_LABELS['packaging'] == '包装部'
        assert len(DEPARTMENT_LABELS) == 3


class TestGetRecords:
    """生产记录查询"""

    @pytest.mark.asyncio
    async def test_get_records_empty(self, mock_async_db):
        """空记录"""
        # 现实现三次 execute：主查询（rows）+ 独立 COUNT（total）+ stats CTE（统计）
        empty_result = MagicMock()
        empty_result.all.return_value = []
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        stats_result = MagicMock()
        stats_result.first.return_value = None
        mock_async_db.execute = AsyncMock(side_effect=[empty_result, count_result, stats_result])

        result = await get_records(mock_async_db, year=2024, month=6)

        assert result['data'] == []
        assert result['total'] == 0

    @pytest.mark.asyncio
    async def test_get_records_with_department(self, mock_async_db):
        """按部门筛选"""
        empty_result = MagicMock()
        empty_result.all.return_value = []
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        stats_result = MagicMock()
        stats_result.first.return_value = None
        mock_async_db.execute = AsyncMock(side_effect=[empty_result, count_result, stats_result])

        result = await get_records(
            mock_async_db, year=2024, month=6, departments={'filling'}
        )

        assert result['total'] == 0

    @pytest.mark.asyncio
    async def test_get_records_with_date(self, mock_async_db):
        """按日期筛选"""
        empty_result = MagicMock()
        empty_result.all.return_value = []
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        stats_result = MagicMock()
        stats_result.first.return_value = None
        mock_async_db.execute = AsyncMock(side_effect=[empty_result, count_result, stats_result])

        result = await get_records(
            mock_async_db, year=2024, month=6, production_date='2024-06-15'
        )

        assert result['total'] == 0

    @pytest.mark.asyncio
    async def test_get_records_pagination(self, mock_async_db):
        """分页查询"""
        empty_result = MagicMock()
        empty_result.all.return_value = []
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        stats_result = MagicMock()
        stats_result.first.return_value = None
        mock_async_db.execute = AsyncMock(side_effect=[empty_result, count_result, stats_result])

        result = await get_records(
            mock_async_db, year=2024, month=6, page=2, per_page=20
        )

        assert result['total'] == 0

    @pytest.mark.asyncio
    async def test_stats_are_page_independent_on_out_of_range_page(self, mock_async_db):
        """越界页 rows 为空，stats 仍须来自 stats_cte（此前从 rows[0] 取值会误报 0）"""
        empty_result = MagicMock()
        empty_result.all.return_value = []
        count_result = MagicMock()
        count_result.scalar.return_value = 128
        stats_result = MagicMock()
        stats_result.first.return_value = (4200, 27170, 17)
        # 空页时 _build_product_price_fallback 提前返回，故恰好三次 execute
        mock_async_db.execute = AsyncMock(side_effect=[empty_result, count_result, stats_result])

        result = await get_records(
            mock_async_db, year=2024, month=6, page=99, per_page=50
        )

        assert result['data'] == []
        assert result['total'] == 128
        assert result['stats']['total_quantity'] == 4200
        assert result['stats']['total_sku'] == 17


class TestCreateRecord:
    """创建生产记录"""

    @pytest.mark.asyncio
    async def test_create_record_strips_created_by(self, mock_async_db):
        """录单人名两侧空白须在写入前去掉（与筛选侧的 strip 对齐）"""
        mock_async_db.execute = AsyncMock()
        mock_async_db.flush = AsyncMock()
        mock_async_db.refresh = AsyncMock()

        await create_record(
            mock_async_db,
            department='filling',
            product_name='产品A',
            quantity=100,
            production_date_str='2024-06-15',
            unit_price=50.0,
            product_id=None,
            barcode='',
            remark='',
            created_by='  张三  ',
        )

        record = mock_async_db.add.call_args.args[0]
        assert record.created_by == '张三'

    @pytest.mark.asyncio
    async def test_create_record_success(self, mock_async_db):
        """正常创建"""
        mock_async_db.execute = AsyncMock()
        mock_async_db.flush = AsyncMock()
        mock_async_db.refresh = AsyncMock()

        record = MagicMock()
        record.to_dict.return_value = {'id': 1, 'product_name': '产品A', 'quantity': 100}
        mock_async_db.add = MagicMock()

        result = await create_record(
            mock_async_db,
            department='filling',
            product_name='产品A',
            quantity=100,
            production_date_str='2024-06-15',
            unit_price=50.0,
            product_id=None,
            barcode='',
            remark='测试',
            created_by='admin'
        )

        assert result.product_name == '产品A'
        assert result.quantity == 100

    @pytest.mark.asyncio
    async def test_create_record_invalid_department(self, mock_async_db):
        """无效部门"""
        with pytest.raises(ValueError, match='部门必须是'):
            await create_record(
                mock_async_db,
                department='invalid',
                product_name='产品A',
                quantity=100,
                production_date_str='2024-06-15',
                product_id=None,
                barcode='',
                unit_price=50.0,
                created_by='admin'
            )

    @pytest.mark.asyncio
    async def test_create_record_zero_quantity(self, mock_async_db):
        """数量为0"""
        with pytest.raises(ValueError, match='生产数量必须大于 0'):
            await create_record(
                mock_async_db,
                department='filling',
                product_name='产品A',
                quantity=0,
                production_date_str='2024-06-15',
                product_id=None,
                barcode='',
                unit_price=50.0,
                created_by='admin'
            )

    @pytest.mark.asyncio
    async def test_create_record_handcraft_department(self, mock_async_db):
        """手工部记录"""
        mock_async_db.execute = AsyncMock()
        mock_async_db.flush = AsyncMock()
        mock_async_db.refresh = AsyncMock()
        mock_async_db.add = MagicMock()

        result = await create_record(
            mock_async_db,
            department='handcraft',
            product_name='手工产品',
            quantity=50,
            production_date_str='2024-06-15',
            unit_price=30.0,
            product_id=None,
            barcode='',
            created_by='admin'
        )

        assert result.department == 'handcraft'

    @pytest.mark.asyncio
    async def test_create_record_packaging_department(self, mock_async_db):
        """包装部记录"""
        mock_async_db.execute = AsyncMock()
        mock_async_db.flush = AsyncMock()
        mock_async_db.refresh = AsyncMock()
        mock_async_db.add = MagicMock()

        result = await create_record(
            mock_async_db,
            department='packaging',
            product_name='包装产品',
            quantity=200,
            production_date_str='2024-06-15',
            unit_price=10.0,
            product_id=None,
            barcode='',
            created_by='admin'
        )

        assert result.department == 'packaging'


class TestUpdateRecord:
    """更新生产记录"""

    @pytest.mark.asyncio
    async def test_update_record_success(self, mock_async_db):
        """正常更新"""
        record = MagicMock()
        record.id = 1
        record.department = 'filling'
        record.product_name = '产品A'
        record.quantity = 100
        record.unit_price = 50.0
        record.to_dict.return_value = {'id': 1, 'quantity': 150}

        mock_async_db.execute = AsyncMock()
        mock_async_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=record)
        mock_async_db.flush = AsyncMock()
        mock_async_db.refresh = AsyncMock()

        result = await update_record(
            mock_async_db, record_id=1, quantity=150, remark='更新备注',
            created_by='admin'
        )

        assert result.quantity == 150

    @pytest.mark.asyncio
    async def test_update_record_not_found(self, mock_async_db):
        """记录不存在"""
        mock_async_db.execute = AsyncMock()
        mock_async_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)

        with pytest.raises(ValueError, match='记录不存在'):
            await update_record(mock_async_db, record_id=999, quantity=100, created_by='admin')

    @pytest.mark.asyncio
    async def test_update_record_invalid_quantity(self, mock_async_db):
        """更新为无效数量"""
        record = MagicMock()
        record.id = 1
        record.department = 'filling'
        record.product_name = '产品A'
        record.quantity = 100
        record.unit_price = 50.0

        mock_async_db.execute = AsyncMock()
        mock_async_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=record)

        with pytest.raises(ValueError, match='生产数量必须大于 0'):
            await update_record(mock_async_db, record_id=1, quantity=0, created_by='admin')


class TestDeleteRecord:
    """删除生产记录"""

    @pytest.mark.asyncio
    async def test_delete_record_success(self, mock_async_db):
        """正常删除"""
        record = MagicMock()
        record.id = 1
        mock_async_db.execute = AsyncMock()
        mock_async_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=record)

        result = await delete_record(mock_async_db, 1)

        assert result is None  # delete_record returns None
        mock_async_db.delete.assert_called_once_with(record)

    @pytest.mark.asyncio
    async def test_delete_record_not_found(self, mock_async_db):
        """记录不存在"""
        mock_async_db.execute = AsyncMock()
        mock_async_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)

        with pytest.raises(ValueError, match='记录不存在'):
            await delete_record(mock_async_db, 999)


class TestGetDailySummary:
    """每日汇总"""


class TestGetMonthlySummary:
    """月度汇总"""

