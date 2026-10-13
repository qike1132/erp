"""order_batch_service.py 中提取的 helper 函数 - 单元测试

覆盖 P1-1 重构提取的 helper：
- _build_batch_order_branch / _build_batch_stockin_branch（SQL 分支构建）
- _serialize_batch_orders / _serialize_batch_stockins（回表序列化）
"""
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.services import order_batch_service


# ============================================================================
# _build_batch_order_branch
# ============================================================================
class TestBuildBatchOrderBranch:
    def test_build_order_branch_minimal_returns_select_with_base_columns(self):
        """无筛选条件时应返回包含 base 列的 select 语句"""
        branch = order_batch_service._build_batch_order_branch(
            whitelist=None, batch_no=None, status=None, customer=None, keyword=None,
        )
        compiled = str(branch.compile())
        assert 'sort_date' in compiled or 'order_date' in compiled
        assert 'is_deleted' in compiled

    def test_build_order_branch_with_whitelist_applies_in_filter(self):
        """whitelist 非空时应添加 customer IN (...) 条件"""
        branch = order_batch_service._build_batch_order_branch(
            whitelist=["客户A", "客户B"], batch_no=None, status=None, customer=None, keyword=None,
        )
        compiled = str(branch.compile())
        assert 'customer' in compiled

    def test_build_order_branch_with_batch_no_filter(self):
        """batch_no 非空时应添加 batch_no 等值条件"""
        branch = order_batch_service._build_batch_order_branch(
            whitelist=None, batch_no="BATCH-001", status=None, customer=None, keyword=None,
        )
        compiled = str(branch.compile())
        assert 'batch_no' in compiled

    def test_build_order_branch_with_status_filter(self):
        """status 非空时应添加 status 等值条件"""
        branch = order_batch_service._build_batch_order_branch(
            whitelist=None, batch_no=None, status="待备货", customer=None, keyword=None,
        )
        compiled = str(branch.compile())
        assert 'status' in compiled

    def test_build_order_branch_with_customer_filter(self):
        """customer 非空时应添加 customer 等值条件"""
        branch = order_batch_service._build_batch_order_branch(
            whitelist=None, batch_no=None, status=None, customer="MINISO", keyword=None,
        )
        compiled = str(branch.compile())
        assert 'customer' in compiled

    def test_build_order_branch_with_keyword_joins_product(self):
        """keyword 非空时应 JOIN Product 表并添加 ilike 条件"""
        branch = order_batch_service._build_batch_order_branch(
            whitelist=None, batch_no=None, status=None, customer=None, keyword="测试",
        )
        compiled = str(branch.compile())
        assert 'product' in compiled.lower()


# ============================================================================
# _build_batch_stockin_branch
# ============================================================================
class TestBuildBatchStockinBranch:
    def test_build_stockin_branch_minimal(self):
        """无筛选条件时应返回包含 base 列的 select 语句"""
        branch = order_batch_service._build_batch_stockin_branch(
            whitelist=None, customer=None, keyword=None,
        )
        compiled = str(branch.compile())
        assert 'stockin' in compiled.lower()

    def test_build_stockin_branch_with_whitelist(self):
        """whitelist 非空时应添加 customer IN 条件"""
        branch = order_batch_service._build_batch_stockin_branch(
            whitelist=["客户A"], customer=None, keyword=None,
        )
        compiled = str(branch.compile())
        assert 'customer' in compiled

    def test_build_stockin_branch_with_customer(self):
        """customer 非空时应添加 customer 等值条件"""
        branch = order_batch_service._build_batch_stockin_branch(
            whitelist=None, customer="MINISO", keyword=None,
        )
        compiled = str(branch.compile())
        assert 'customer' in compiled

    def test_build_stockin_branch_with_keyword_joins_product(self):
        """keyword 非空时应 JOIN Product 表"""
        branch = order_batch_service._build_batch_stockin_branch(
            whitelist=None, customer=None, keyword="商品",
        )
        compiled = str(branch.compile())
        assert 'product' in compiled.lower()


# ============================================================================
# _serialize_batch_orders
# ============================================================================
class TestSerializeBatchOrders:
    @pytest.mark.asyncio
    async def test_serialize_empty_ids_returns_empty_dict(self):
        """空 ID 列表应直接返回空字典，不查询数据库"""
        db = AsyncMock()
        result = await order_batch_service._serialize_batch_orders(db, [])
        assert result == {}
        assert db.execute.await_count == 0

    @pytest.mark.asyncio
    async def test_serialize_orders_with_stockout_data(self):
        """有订单和出货数据时应正确序列化并附加 computed_status"""
        mock_order = MagicMock()
        mock_order.id = 1
        mock_order.order_no = "PO-001"
        mock_order.customer = "客户A"
        mock_order.product = MagicMock(barcode="690001")
        mock_order.batch_no = "B001"

        order_result = MagicMock()
        order_result.unique.return_value.scalars.return_value.all.return_value = [mock_order]

        stockout_result = MagicMock()
        # __iter__ 使 for order_id, stockin_id, qty in stockout_result 可迭代
        stockout_result.__iter__ = MagicMock(return_value=iter([(1, 100, 5), (1, None, 3)]))

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[order_result, stockout_result])

        with patch('fastapi_app.services.serializers.order_serializer.OrderSerializer.serialize',
                   return_value={'id': 1, 'order_no': 'PO-001'}), \
             patch('fastapi_app.shared_models.order.compute_status_from_stockouts',
                   return_value='部分出货'):
            result = await order_batch_service._serialize_batch_orders(db, [1])

        assert 1 in result
        assert result[1]['deducted_qty'] == 5
        assert result[1]['shipped_qty'] == 3
        assert result[1]['computed_status'] == '部分出货'
        assert result[1]['record_type'] == 'order'
        assert result[1]['product_barcode'] == '690001'

    @pytest.mark.asyncio
    async def test_serialize_orders_handles_none_qty(self):
        """StockOut qty 为 None 时应跳过该行"""
        mock_order = MagicMock()
        mock_order.id = 2
        mock_order.order_no = "PO-002"
        mock_order.product = MagicMock(barcode="690002")
        mock_order.batch_no = None

        order_result = MagicMock()
        order_result.unique.return_value.scalars.return_value.all.return_value = [mock_order]

        stockout_result = MagicMock()
        stockout_result.__iter__ = MagicMock(return_value=iter([(2, 100, None)]))

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[order_result, stockout_result])

        with patch('fastapi_app.services.serializers.order_serializer.OrderSerializer.serialize',
                   return_value={'id': 2}), \
             patch('fastapi_app.shared_models.order.compute_status_from_stockouts',
                   return_value='待备货'):
            result = await order_batch_service._serialize_batch_orders(db, [2])

        # None qty 被跳过，使用默认 0
        assert result[2]['deducted_qty'] == 0
        assert result[2]['shipped_qty'] == 0


# ============================================================================
# _serialize_batch_stockins
# ============================================================================
class TestSerializeBatchStockins:
    @pytest.mark.asyncio
    async def test_serialize_empty_ids_returns_empty_dict(self):
        """空 ID 列表应直接返回空字典"""
        db = AsyncMock()
        result = await order_batch_service._serialize_batch_stockins(db, [])
        assert result == {}
        assert db.execute.await_count == 0

    @pytest.mark.asyncio
    async def test_serialize_stockins_with_product(self):
        """有备货记录时应正确序列化含产品信息"""
        mock_stockin = MagicMock()
        mock_stockin.id = 10
        mock_stockin.stockin_no = "SI-001"
        mock_stockin.customer = "客户B"
        mock_stockin.stockin_date = datetime(2026, 1, 15, 10, 30)
        mock_stockin.product_id = 5
        product = MagicMock()
        product.name = "产品X"
        product.barcode = "690005"
        mock_stockin.product = product
        mock_stockin.quantity = 20

        result_mock = MagicMock()
        result_mock.unique.return_value.scalars.return_value.all.return_value = [mock_stockin]

        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        result = await order_batch_service._serialize_batch_stockins(db, [10])

        assert 10 in result
        item = result[10]
        assert item['order_no'] == 'SI-001'
        assert item['customer'] == '客户B'
        assert item['product_name'] == '产品X'
        assert item['product_barcode'] == '690005'
        assert item['quantity'] == 20
        assert item['record_type'] == 'stockin'
        assert item['deducted_qty'] == 0
        assert item['shipped_qty'] == 0

    @pytest.mark.asyncio
    async def test_serialize_stockins_none_date(self):
        """stockin_date 为 None 时 order_no 字段应为空字符串"""
        mock_stockin = MagicMock()
        mock_stockin.id = 11
        mock_stockin.stockin_no = "SI-002"
        mock_stockin.customer = "客户C"
        mock_stockin.stockin_date = None
        mock_stockin.product_id = 6
        product = MagicMock()
        product.name = "产品Y"
        product.barcode = "690006"
        mock_stockin.product = product
        mock_stockin.quantity = 5

        result_mock = MagicMock()
        result_mock.unique.return_value.scalars.return_value.all.return_value = [mock_stockin]

        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        result = await order_batch_service._serialize_batch_stockins(db, [11])
        assert result[11]['order_date'] == ''

    @pytest.mark.asyncio
    async def test_serialize_stockins_none_product(self):
        """product 为 None 时产品名/条码应为 None"""
        mock_stockin = MagicMock()
        mock_stockin.id = 12
        mock_stockin.stockin_no = "SI-003"
        mock_stockin.customer = "客户D"
        mock_stockin.stockin_date = datetime(2026, 2, 1)
        mock_stockin.product_id = 7
        mock_stockin.product = None
        mock_stockin.quantity = 1

        result_mock = MagicMock()
        result_mock.unique.return_value.scalars.return_value.all.return_value = [mock_stockin]

        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        result = await order_batch_service._serialize_batch_stockins(db, [12])
        assert result[12]['product_name'] is None
        assert result[12]['product_barcode'] is None

    @pytest.mark.asyncio
    async def test_serialize_stockins_includes_batch_fields(self):
        """备货序列化应带上真实 batch_no / batch_completed_at；未完成时 status 为 None"""
        mock_stockin = MagicMock()
        mock_stockin.id = 20
        mock_stockin.stockin_no = "SI-020"
        mock_stockin.customer = "客户E"
        mock_stockin.stockin_date = datetime(2026, 3, 1, 9, 0)
        mock_stockin.product_id = 8
        product = MagicMock()
        product.name = "产品Z"
        product.barcode = "690008"
        mock_stockin.product = product
        mock_stockin.quantity = 7
        mock_stockin.batch_no = "B2026"
        mock_stockin.batch_completed_at = None

        result_mock = MagicMock()
        result_mock.unique.return_value.scalars.return_value.all.return_value = [mock_stockin]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        result = await order_batch_service._serialize_batch_stockins(db, [20])
        assert result[20]['batch_no'] == 'B2026'
        assert result[20]['batch_completed_at'] is None
        assert result[20]['status'] is None

    @pytest.mark.asyncio
    async def test_serialize_stockins_completed_sets_status(self):
        """已完成的备货 status 应为 '批次已完成'，batch_completed_at 为字符串"""
        mock_stockin = MagicMock()
        mock_stockin.id = 21
        mock_stockin.stockin_no = "SI-021"
        mock_stockin.customer = "客户F"
        mock_stockin.stockin_date = datetime(2026, 3, 2, 9, 0)
        mock_stockin.product_id = 9
        mock_stockin.product = None
        mock_stockin.quantity = 3
        mock_stockin.batch_no = "B2026"
        mock_stockin.batch_completed_at = datetime(2026, 3, 3, 12, 0)

        result_mock = MagicMock()
        result_mock.unique.return_value.scalars.return_value.all.return_value = [mock_stockin]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        result = await order_batch_service._serialize_batch_stockins(db, [21])
        assert result[21]['status'] == '批次已完成'
        assert result[21]['batch_completed_at'] == '2026-03-03 12:00'


# ============================================================================
# update_stockin_batch_no
# ============================================================================
class TestUpdateStockinBatchNo:
    @pytest.mark.asyncio
    async def test_sets_batch_no(self):
        """写 StockIn.batch_no，不涉及订单同步"""
        mock_stockin = MagicMock()
        mock_stockin.id = 30
        mock_stockin.batch_no = None
        result = MagicMock()
        result.scalar_one_or_none.return_value = mock_stockin
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result)

        user = MagicMock()
        user.id = 1
        user.username = "admin"

        with patch('fastapi_app.services.order_batch_service._safe_publish_event', new=AsyncMock()), \
             patch('fastapi_app.services.order_batch_service._write_audit_log'):
            out = await order_batch_service.update_stockin_batch_no(
                db, stockin_id=30, batch_no='B9', user=user,
            )
        assert mock_stockin.batch_no == 'B9'
        assert out['updated_count'] == 1

    @pytest.mark.asyncio
    async def test_missing_raises(self):
        """备货不存在应抛 ValueError"""
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result)
        with pytest.raises(ValueError):
            await order_batch_service.update_stockin_batch_no(
                db, stockin_id=999, batch_no='B9', user=MagicMock(),
            )

    @pytest.mark.asyncio
    async def test_clears_batch_no(self):
        """传 null 清空备货批次号"""
        mock_stockin = MagicMock()
        mock_stockin.id = 31
        mock_stockin.batch_no = 'OLD'
        result = MagicMock()
        result.scalar_one_or_none.return_value = mock_stockin
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result)
        with patch('fastapi_app.services.order_batch_service._safe_publish_event', new=AsyncMock()), \
             patch('fastapi_app.services.order_batch_service._write_audit_log'):
            await order_batch_service.update_stockin_batch_no(
                db, stockin_id=31, batch_no=None, user=MagicMock(),
            )
        assert mock_stockin.batch_no is None


# ============================================================================
# complete_batch（含备货）
# ============================================================================
class TestCompleteBatchStockins:
    @pytest.mark.asyncio
    async def test_completes_stockins_of_batch(self):
        """完成批次时该批次未完成的备货也被标记完成"""
        mock_stockin = MagicMock()
        mock_stockin.id = 40
        mock_stockin.batch_completed_at = None
        stockin_result = MagicMock()
        stockin_result.scalars.return_value.all.return_value = [mock_stockin]

        order_result = MagicMock()
        order_result.scalars.return_value.all.return_value = []  # 无订单

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[order_result, stockin_result])

        user = MagicMock()
        user.id = 1
        user.username = "admin"

        with patch('fastapi_app.services.order_batch_service._safe_publish_event', new=AsyncMock()), \
             patch('fastapi_app.services.order_batch_service._write_audit_log'):
            out = await order_batch_service.complete_batch(db, batch_no='B9', user=user)

        assert mock_stockin.batch_completed_at is not None
        assert mock_stockin.batch_completed_by_id == 1
        assert out['completed_stockins'] == 1

    @pytest.mark.asyncio
    async def test_no_orders_no_stockins_raises(self):
        """订单与备货都为空时应抛 ValueError"""
        empty = MagicMock()
        empty.scalars.return_value.all.return_value = []
        db = AsyncMock()
        db.execute = AsyncMock(return_value=empty)
        with pytest.raises(ValueError):
            await order_batch_service.complete_batch(db, batch_no='B-none', user=MagicMock())

    @pytest.mark.asyncio
    async def test_mixed_batch_order_failed_stockin_completed(self):
        """批次里订单未出货 → 进 failed_orders；备货照常完成"""
        mock_order = MagicMock()
        mock_order.id = 50
        mock_order.order_no = "PO-50"
        mock_order.status = "待出货"  # != ORDER_STATUS_SHIPPED
        order_result = MagicMock()
        order_result.scalars.return_value.all.return_value = [mock_order]

        mock_stockin = MagicMock()
        mock_stockin.id = 51
        mock_stockin.batch_completed_at = None
        stockin_result = MagicMock()
        stockin_result.scalars.return_value.all.return_value = [mock_stockin]

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[order_result, stockin_result])

        user = MagicMock()
        user.id = 1
        user.username = "admin"
        with patch('fastapi_app.services.order_batch_service._safe_publish_event', new=AsyncMock()), \
             patch('fastapi_app.services.order_batch_service._write_audit_log'):
            out = await order_batch_service.complete_batch(db, batch_no='B9', user=user)

        assert out['completed_count'] == 0
        assert len(out['failed_orders']) == 1
        assert out['completed_stockins'] == 1
        assert mock_stockin.batch_completed_at is not None
