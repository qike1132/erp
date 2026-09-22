"""
客户订单 单元测试

覆盖：
- 订单列表查询（分页、多维度筛选、工厂隔离）
- 订单详情查询（含关联数据）
- 订单创建（业务规则校验、库存日志、事件发布）
- 订单编辑（超管直接修改、普通用户提交审批）
- 订单删除（抵扣回滚、关联清理、审批流程）
- 订单抵扣管理（增加抵扣 FIFO、减少抵扣、状态计算）
- 审批取消
- 湖北订单合并列表
- 边界条件（负数数量、不存在的产品、锁定冲突、审批状态检查）
"""
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.services.order_crud import (
    cancel_approval,
    create_order,
    delete_order,
    get_beile_orders_with_stockins,
    get_my_approvals,
    get_order_by_id,
    get_orders,
    update_deduct_quantity,
    update_order,
)


def make_mock_order(id_val=1, order_no='ORD-001', customer='测试客户',
                    quantity=100, status='待备货', order_type='regular'):
    """构造 mock 订单对象"""
    order = MagicMock()
    order.id = id_val
    order.order_no = order_no
    order.customer = customer
    order.quantity = quantity
    order.status = status
    order.order_type = order_type
    order.is_deleted = False
    order.is_locked = False
    order.note = ''
    order.country = None
    order.product_id = 1
    order.product = MagicMock()
    order.product.name = '测试产品'
    order.product.barcode = 'TEST001'
    order.locked_by = None
    order.items = []
    order.order_date = datetime.now(UTC)
    return order


class TestGetOrders:
    """订单列表查询"""

    @pytest.mark.asyncio
    async def test_get_orders_empty(self, mock_async_db):
        """查询空订单列表"""
        count_result = MagicMock()
        count_result.scalar.return_value = 0

        data_result = MagicMock()
        data_result.scalars.return_value.unique.return_value.all.return_value = []

        mock_async_db.execute = AsyncMock()
        mock_async_db.execute.side_effect = [count_result, data_result]

        result = await get_orders(mock_async_db, page=1, per_page=50)

        assert result['items'] == []
        assert result['total'] == 0

    @pytest.mark.asyncio
    @patch('fastapi_app.services.order_crud.get_orders')
    async def test_get_orders_with_data(self, mock_get):
        """查询有数据的订单列表"""
        mock_get.return_value = {
            'items': [{'id': 1, 'order_no': 'ORD-001'}],
            'total': 10,
            'page': 1,
            'per_page': 50,
        }

        result = await mock_get(MagicMock(), page=1, per_page=50)

        assert result['total'] == 10
        assert len(result['items']) == 1

    @pytest.mark.asyncio
    async def test_get_orders_with_customer_filter(self, mock_async_db):
        """按客户筛选订单"""
        count_result = MagicMock()
        count_result.scalar.return_value = 3

        data_result = MagicMock()
        data_result.scalars.return_value.unique.return_value.all.return_value = []
        mock_async_db.execute = AsyncMock()
        mock_async_db.execute.side_effect = [count_result, data_result]

        result = await get_orders(mock_async_db, page=1, customer='测试客户')

        assert result['total'] == 3

    @pytest.mark.asyncio
    async def test_get_orders_with_status_filter(self, mock_async_db):
        """按状态筛选"""
        count_result = MagicMock()
        count_result.scalar.return_value = 5

        data_result = MagicMock()
        data_result.scalars.return_value.unique.return_value.all.return_value = []
        mock_async_db.execute = AsyncMock()
        mock_async_db.execute.side_effect = [count_result, data_result]

        result = await get_orders(mock_async_db, page=1, status='待备货')

        assert result['total'] == 5

    @pytest.mark.asyncio
    async def test_get_orders_with_factory_filter(self, mock_async_db):
        """按工厂筛选"""
        count_result = MagicMock()
        count_result.scalar.return_value = 2

        data_result = MagicMock()
        data_result.scalars.return_value.unique.return_value.all.return_value = []
        mock_async_db.execute = AsyncMock()
        mock_async_db.execute.side_effect = [count_result, data_result]

        result = await get_orders(mock_async_db, page=1, factory='湖北')

        assert result['total'] == 2

    @pytest.mark.asyncio
    async def test_get_orders_with_date_range(self, mock_async_db):
        """按日期范围筛选"""
        count_result = MagicMock()
        count_result.scalar.return_value = 7

        data_result = MagicMock()
        data_result.scalars.return_value.unique.return_value.all.return_value = []
        mock_async_db.execute = AsyncMock()
        mock_async_db.execute.side_effect = [count_result, data_result]

        result = await get_orders(
            mock_async_db, page=1,
            start_date='2024-01-01', end_date='2024-12-31'
        )

        assert result['total'] == 7


class TestGetOrderById:
    """订单详情查询"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.order.queries._batch_deduct_quantities')
    @patch('fastapi_app.services.order.queries.OrderSerializer')
    async def test_get_order_by_id_success(self, mock_serializer, mock_batch_deduct,
                                            mock_async_db):
        """查询订单详情"""
        order = make_mock_order()
        data_result = MagicMock()
        data_result.scalars.return_value.unique.return_value.first.return_value = order
        mock_async_db.execute = AsyncMock(return_value=data_result)
        mock_batch_deduct.return_value = {1: 5}
        mock_serializer.serialize.return_value = {'id': 1, 'order_no': 'ORD-001'}

        result = await get_order_by_id(mock_async_db, 1)

        assert result['order_no'] == 'ORD-001'

    @pytest.mark.asyncio
    async def test_get_order_by_id_not_found(self, mock_async_db):
        """查询不存在的订单"""
        data_result = MagicMock()
        data_result.scalars.return_value.unique.return_value.first.return_value = None
        mock_async_db.execute = AsyncMock(return_value=data_result)

        result = await get_order_by_id(mock_async_db, 999)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_order_by_id_deleted_order(self, mock_async_db):
        """已删除订单查不到"""
        data_result = MagicMock()
        data_result.scalars.return_value.unique.return_value.first.return_value = None
        mock_async_db.execute = AsyncMock(return_value=data_result)

        result = await get_order_by_id(mock_async_db, 999)

        assert result is None


class TestCreateOrder:
    """订单创建"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.order_crud.create_order')
    async def test_create_order_success(self, mock_create, mock_user):
        """正常创建订单"""
        mock_create.return_value = {
            'order_no': 'ORD-2024-001',
            'customer': '测试客户',
            'status': '待备货',
        }

        result = await mock_create(
            MagicMock(),
            product_id=1,
            quantity=50,
            customer='测试客户',
            note='测试备注',
            current_user=mock_user,
            order_type='regular'
        )

        assert result['customer'] == '测试客户'
        assert result['status'] == '待备货'

    @pytest.mark.asyncio
    async def test_create_order_custom_without_country(self, mock_async_db, mock_user):
        """定制订单未填写国家 - 应报错"""
        with pytest.raises(ValueError, match='定制订单必须填写国家名称'):
            await create_order(
                mock_async_db, product_id=1, quantity=50,
                customer='客户', note='', current_user=mock_user,
                order_type='custom', country=None
            )

    @pytest.mark.asyncio
    @patch('fastapi_app.services.order_crud.create_order')
    async def test_create_order_custom_with_country(self, mock_create, mock_user):
        """定制订单 - 填写国家"""
        mock_create.return_value = {
            'order_no': 'ORD-001',
            'customer': '客户',
            'status': '待备货',
            'order_type': 'custom',
            'country': '美国',
        }

        result = await mock_create(
            MagicMock(), product_id=1, quantity=50,
            customer='客户', note='', current_user=mock_user,
            order_type='custom', country='美国'
        )

        assert result['status'] == '待备货'

    @pytest.mark.asyncio
    async def test_create_order_zero_quantity(self, mock_async_db, mock_user):
        """数量为0"""
        with pytest.raises(ValueError):
            await create_order(
                mock_async_db, product_id=1, quantity=0,
                customer='客户', note='', current_user=mock_user
            )

    @pytest.mark.asyncio
    @patch('fastapi_app.services.order.commands.get_product_for_update')
    async def test_create_order_negative_quantity(self, mock_get_product,
                                                    mock_async_db, mock_user):
        """数量为负数"""
        product = MagicMock()
        product.id = 1
        mock_get_product.return_value = product

        with pytest.raises(ValueError):
            await create_order(
                mock_async_db, product_id=1, quantity=-5,
                customer='客户', note='', current_user=mock_user
            )

    @pytest.mark.asyncio
    @patch('fastapi_app.services.order.commands.get_product_for_update')
    async def test_create_order_quantity_too_large(self, mock_get_product,
                                                     mock_async_db, mock_user):
        """数量超过上限"""
        product = MagicMock()
        product.id = 1
        mock_get_product.return_value = product

        with pytest.raises(ValueError):
            await create_order(
                mock_async_db, product_id=1, quantity=10000000,
                customer='客户', note='', current_user=mock_user
            )


class TestUpdateOrder:
    """订单编辑"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.order.commands.cache_mgr')
    async def test_update_order_not_found(self, mock_cache, mock_async_db, mock_user):
        """编辑不存在的订单"""
        data_result = MagicMock()
        data_result.scalar_one_or_none.return_value = None
        mock_async_db.execute = AsyncMock(return_value=data_result)

        with pytest.raises(ValueError, match='订单不存在'):
            await update_order(
                mock_async_db, order_id=999, quantity=50,
                customer='客户', note='', current_user=mock_user
            )

    @pytest.mark.asyncio
    @patch('fastapi_app.services.order.commands.cache_mgr')
    async def test_update_order_deleted(self, mock_cache, mock_async_db, mock_user):
        """编辑已删除的订单"""
        order = make_mock_order()
        order.is_deleted = True
        data_result = MagicMock()
        data_result.scalar_one_or_none.return_value = order
        mock_async_db.execute = AsyncMock(return_value=data_result)

        with pytest.raises(ValueError, match='订单不存在'):
            await update_order(
                mock_async_db, order_id=1, quantity=50,
                customer='客户', note='', current_user=mock_user
            )

    @pytest.mark.asyncio
    @patch('fastapi_app.services.order.commands.cache_mgr')
    @patch('fastapi_app.services.order.commands._check_order_lock')
    async def test_update_order_super_admin_direct(self, mock_check_lock, mock_cache,
                                                     mock_async_db):
        """超管直接编辑订单（无需审批）"""
        order = make_mock_order()
        data_result = MagicMock()
        data_result.scalar_one_or_none.return_value = order
        mock_async_db.execute = AsyncMock(return_value=data_result)

        super_user = MagicMock()
        super_user.id = 1
        super_user.username = 'admin'
        super_user.is_super = True

        with patch('fastapi_app.services.order.commands._update_order_directly',
                   return_value={'success': True, 'message': '订单编辑成功！',
                                'requires_approval': False}):
            result = await update_order(
                mock_async_db, order_id=1, quantity=30,
                customer='新客户', note='新备注',
                current_user=super_user
            )

        assert result['success'] is True

    @pytest.mark.asyncio
    @patch('fastapi_app.services.order.commands.cache_mgr')
    @patch('fastapi_app.services.order.commands._check_order_lock')
    @patch('fastapi_app.services.order.commands._submit_edit_approval')
    async def test_update_order_normal_user_approval(self, mock_submit, mock_check_lock,
                                                       mock_cache, mock_async_db):
        """普通用户编辑订单 - 走审批流程"""
        order = make_mock_order()
        data_result = MagicMock()
        data_result.scalar_one_or_none.return_value = order
        mock_async_db.execute = AsyncMock(return_value=data_result)

        normal_user = MagicMock()
        normal_user.id = 2
        normal_user.username = 'user1'
        normal_user.is_super = False

        mock_submit.return_value = {
            'success': True,
            'message': '已提交编辑审批请求',
            'requires_approval': True
        }

        result = await update_order(
            mock_async_db, order_id=1, quantity=20,
            customer='新客户', note='新备注',
            current_user=normal_user
        )

        assert result['requires_approval'] is True


class TestDeleteOrder:
    """订单删除"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.order.commands.cache_mgr')
    async def test_delete_order_not_found(self, mock_cache, mock_async_db, mock_user):
        """删除不存在的订单"""
        mock_async_db.get = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match='订单不存在'):
            await delete_order(mock_async_db, 999, mock_user)

    @pytest.mark.asyncio
    @patch('fastapi_app.services.order.commands.cache_mgr')
    @patch('fastapi_app.services.order.commands._check_order_lock')
    @patch('fastapi_app.services.order.commands._submit_delete_approval')
    async def test_delete_order_normal_user(self, mock_submit, mock_check_lock,
                                              mock_cache, mock_async_db):
        """普通用户删除订单 - 走审批"""
        order = make_mock_order()
        mock_async_db.get = AsyncMock(return_value=order)

        normal_user = MagicMock()
        normal_user.id = 2
        normal_user.is_super = False

        mock_submit.return_value = {
            'success': True,
            'message': '已提交删除审批请求',
            'requires_approval': True
        }

        result = await delete_order(mock_async_db, 1, normal_user)

        assert result['requires_approval'] is True

    @pytest.mark.asyncio
    @patch('fastapi_app.services.order.commands.cache_mgr')
    @patch('fastapi_app.services.order.commands._check_order_lock')
    @patch('fastapi_app.services.order.commands._delete_order_directly')
    @patch('fastapi_app.services.order.commands._safe_publish_event')
    async def test_delete_order_super_admin(self, mock_publish, mock_direct,
                                              mock_check_lock, mock_cache,
                                              mock_async_db):
        """超管直接删除订单"""
        order = make_mock_order()
        mock_async_db.get = AsyncMock(return_value=order)

        super_user = MagicMock()
        super_user.id = 1
        super_user.is_super = True

        mock_direct.return_value = {'success': True, 'message': '删除成功', 'requires_approval': False}

        result = await delete_order(mock_async_db, 1, super_user)

        assert result['success'] is True


class TestCancelApproval:
    """审批取消"""

    @pytest.mark.asyncio
    async def test_cancel_approval_not_found(self, mock_async_db, mock_user):
        """取消不存在的审批"""
        mock_async_db.get = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match='审批请求不存在'):
            await cancel_approval(mock_async_db, 999, mock_user)

    @pytest.mark.asyncio
    @patch('fastapi_app.services.order.approval_flow.can_transition')
    async def test_cancel_approval_invalid_status(self, mock_can_transition,
                                                    mock_async_db, mock_user):
        """取消已审批的记录"""
        approval = MagicMock()
        approval.id = 1
        approval.status = 'approved'
        approval.requester_id = 1
        mock_async_db.get = AsyncMock(return_value=approval)
        mock_can_transition.return_value = False

        with pytest.raises(ValueError, match='无法取消'):
            await cancel_approval(mock_async_db, 1, mock_user)


class TestGetBeileOrders:
    """湖北订单合并列表"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.order.beile.get_beile_unconfirmed_count',
           new_callable=AsyncMock, return_value=0)
    async def test_get_beile_orders_empty(self, _mock_unconfirmed, mock_async_db):
        """湖北订单列表 - 空"""
        # 现实现：分页窗口查询（all()），无行且 offset=0 → 直接空页返回
        page_result = MagicMock()
        page_result.all.return_value = []
        mock_async_db.execute = AsyncMock(return_value=page_result)

        result = await get_beile_orders_with_stockins(mock_async_db, page=1)

        assert result['items'] == []
        assert result['total'] == 0

    @pytest.mark.asyncio
    @patch('fastapi_app.services.order.beile.get_beile_unconfirmed_count',
           new_callable=AsyncMock, return_value=0)
    async def test_get_beile_orders_with_customer_filter(self, _mock_unconfirmed, mock_async_db):
        """湖北订单 - 按客户筛选"""
        page_result = MagicMock()
        page_result.all.return_value = []
        mock_async_db.execute = AsyncMock(return_value=page_result)

        result = await get_beile_orders_with_stockins(
            mock_async_db, page=1, customer='湖北客户'
        )

        assert result['items'] == []
        assert result['total'] == 0


class TestBeileSoftDeleteFilter:
    """湖北订单软删除过滤（Order.is_deleted 与 StockIn.is_deleted 语义对齐）

    用真实 SQLite 执行 UNION 子查询，验证软删行不出现在合并列表：
    若 StockIn 侧丢失 is_deleted 过滤，软删备货行会重新混入列表与计数。
    """

    @staticmethod
    async def _session(tmp_path):
        """真实 SQLite 库（只建 union 涉及的表及其外键依赖，避开 JSONB 等 PG 专属列）"""
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from fastapi_app.shared_models import Base

        # 外键链：order/order_item/stock_in → product/user
        needed = {'order', 'order_item', 'stock_in', 'product', 'user'}
        tables = [t for t in Base.metadata.sorted_tables if t.name in needed]
        engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "beile.db"}')
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=tables)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        yield sf, engine

    @pytest.mark.asyncio
    async def test_soft_deleted_stockin_excluded_from_unified_query(self, tmp_path):
        """软删 StockIn 不进合并子查询；未删行正常返回"""
        agen = self._session(tmp_path)
        sf, engine = await agen.__anext__()

        from fastapi_app.services.order.beile import _build_beile_unified_query
        from fastapi_app.shared_models import Product, StockIn
        from sqlalchemy import select as sa_select

        async with sf() as db:
            product = Product(name='软删测试品', factory='湖北')
            db.add(product)
            await db.flush()

            db.add(StockIn(stockin_no='SI-KEEP', customer='客户A', product_id=product.id,
                           quantity=10, confirmed_at=None))
            db.add(StockIn(stockin_no='SI-DELETED', customer='客户B', product_id=product.id,
                           quantity=20, confirmed_at=None, is_deleted=True))
            await db.flush()

            subq = _build_beile_unified_query(confirmed=None, factory='湖北',
                                              customer=None, product_kw=None)
            rows = (await db.execute(sa_select(subq))).all()
            stockin_rows = {r.order_no for r in rows if r.record_type == 'stockin'}

            assert 'SI-KEEP' in stockin_rows, '未软删备货应出现在合并查询中'
            assert 'SI-DELETED' not in stockin_rows, '软删备货不应出现在合并查询中'

        await engine.dispose()

    @pytest.mark.asyncio
    async def test_soft_deleted_order_excluded_from_unified_query(self, tmp_path):
        """软删 Order 不进合并子查询（既有行为的回归锚点）"""
        agen = self._session(tmp_path)
        sf, engine = await agen.__anext__()

        from fastapi_app.services.order.beile import _build_beile_unified_query
        from fastapi_app.shared_models import Order, OrderItem, Product
        from sqlalchemy import select as sa_select

        async with sf() as db:
            product = Product(name='订单软删测试品', factory='湖北')
            db.add(product)
            await db.flush()

            keep = Order(order_no='ORD-KEEP', customer='客户A', product_id=product.id, quantity=10)
            deleted = Order(order_no='ORD-DELETED', customer='客户B', product_id=product.id,
                            quantity=20, is_deleted=True)
            db.add_all([keep, deleted])
            await db.flush()
            # 工厂过滤经 order_item.product 走（无 item 的订单不进合并列表）
            db.add(OrderItem(order_id=keep.id, product_id=product.id,
                             product_name=product.name, quantity=10))
            db.add(OrderItem(order_id=deleted.id, product_id=product.id,
                             product_name=product.name, quantity=20))
            await db.flush()

            subq = _build_beile_unified_query(confirmed=None, factory='湖北',
                                              customer=None, product_kw=None)
            rows = (await db.execute(sa_select(subq))).all()
            order_rows = {r.order_no for r in rows if r.record_type == 'order'}

            assert 'ORD-KEEP' in order_rows
            assert 'ORD-DELETED' not in order_rows

        await engine.dispose()


class TestUpdateDeductQuantity:
    """订单抵扣管理"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.order.deduction.cache_mgr')
    async def test_update_deduct_not_found(self, mock_cache, mock_async_db, mock_user):
        """抵扣修改 - 订单不存在"""
        data_result = MagicMock()
        data_result.scalar_one_or_none.return_value = None
        mock_async_db.execute = AsyncMock(return_value=data_result)

        with pytest.raises(ValueError, match='订单不存在'):
            await update_deduct_quantity(mock_async_db, 999, 10, mock_user)

    @pytest.mark.asyncio
    @patch('fastapi_app.services.order.deduction.cache_mgr')
    @patch('fastapi_app.services.order.deduction._check_order_lock')
    async def test_update_deduct_negative(self, mock_check_lock, mock_cache,
                                            mock_async_db, mock_user):
        """抵扣数量为负"""
        order = make_mock_order()
        data_result = MagicMock()
        data_result.scalar_one_or_none.return_value = order
        mock_async_db.execute = AsyncMock(return_value=data_result)

        with pytest.raises(ValueError, match='抵扣数量不能为负数'):
            await update_deduct_quantity(mock_async_db, 1, -5, mock_user)

    @pytest.mark.asyncio
    @patch('fastapi_app.services.order.deduction.cache_mgr')
    @patch('fastapi_app.services.order.deduction._check_order_lock')
    @patch('fastapi_app.services.order.deduction._batch_deduct_quantities')
    async def test_update_deduct_no_change(self, mock_batch, mock_check_lock,
                                             mock_cache, mock_async_db, mock_user):
        """抵扣数量无变化"""
        order = make_mock_order()
        data_result = MagicMock()
        data_result.scalar_one_or_none.return_value = order
        mock_async_db.execute = AsyncMock(return_value=data_result)
        mock_batch.return_value = {1: 10}

        result = await update_deduct_quantity(mock_async_db, 1, 10, mock_user)

        assert result['deduct_quantity'] == 10
        assert '未变化' in result['message']


class TestGetMyApprovals:
    """我的审批列表"""

    @pytest.mark.asyncio
    async def test_get_my_approvals_empty(self, mock_async_db, mock_user):
        """空审批列表"""
        data_result = MagicMock()
        data_result.scalars.return_value.unique.return_value.all.return_value = []
        mock_async_db.execute = AsyncMock(return_value=data_result)

        result = await get_my_approvals(mock_async_db, mock_user)

        assert result == []

    @pytest.mark.asyncio
    async def test_get_my_approvals_with_data(self, mock_async_db, mock_user):
        """有审批数据"""
        approval = MagicMock()
        approval.to_dict.return_value = {'id': 1, 'status': 'pending'}

        data_result = MagicMock()
        data_result.scalars.return_value.unique.return_value.all.return_value = [approval]
        mock_async_db.execute = AsyncMock(return_value=data_result)

        result = await get_my_approvals(mock_async_db, mock_user)

        assert len(result) == 1
        assert result[0]['status'] == 'pending'
