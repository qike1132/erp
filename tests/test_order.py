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

    @pytest.mark.asyncio
    async def test_create_order_blank_customer_rejected(self, mock_async_db, mock_user):
        """2026-10-17 审计 P2-06：纯空格客户名不得入库（docstring 早已声明）"""
        with pytest.raises(ValueError):
            await create_order(
                mock_async_db, product_id=1, quantity=1,
                customer='   ', note='', current_user=mock_user
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
        # 2026-10-18 P2-07：delete_order 改为 db.execute 取数（先无锁读 product_id，
        # 再 select(Order).with_for_update()），不再走 db.get。两次都返回 None：
        # 第一次跳过预锁，第二次抛「订单不存在」。
        mock_async_db.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=None)))

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
        # 2026-10-19 OCR 第三轮 H2 对齐 M4 重构后的调用序列——
        # _prelock_order_products：① select(Order.product_id) 无锁预读；
        # ② select(StockOut.product_id).distinct() 出库产品集（空）；
        # ③ get_product_for_update 的产品行（product_id=1，一次）；
        # ④ select(Order).with_for_update() 订单行；其后是关联退货查询（空行集）。
        call_count = {'n': 0}

        async def _fake_execute(*_args, **_kwargs):
            call_count['n'] += 1
            if call_count['n'] == 1:
                return MagicMock(scalar_one_or_none=MagicMock(return_value=order.product_id))
            if call_count['n'] == 2:
                return MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))
            if call_count['n'] in (3, 4):
                return MagicMock(scalar_one_or_none=MagicMock(return_value=order))
            return MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))

        mock_async_db.execute = AsyncMock(side_effect=_fake_execute)

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
    @patch('fastapi_app.services.order._common._safe_publish_event')
    async def test_delete_order_super_admin(self, mock_publish, mock_direct,
                                              mock_check_lock, mock_cache,
                                              mock_async_db):
        """超管直接删除订单"""
        order = make_mock_order()
        # 2026-10-19 OCR 第三轮 H2：取数顺序同 test_delete_order_normal_user
        # （① product_id ② 出库产品集 ③ 产品行 ④ 订单行，其后空行集）。
        call_count = {'n': 0}

        async def _fake_execute(*_args, **_kwargs):
            call_count['n'] += 1
            if call_count['n'] == 1:
                return MagicMock(scalar_one_or_none=MagicMock(return_value=order.product_id))
            if call_count['n'] == 2:
                return MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))
            if call_count['n'] in (3, 4):
                return MagicMock(scalar_one_or_none=MagicMock(return_value=order))
            return MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))

        mock_async_db.execute = AsyncMock(side_effect=_fake_execute)

        super_user = MagicMock()
        super_user.id = 1
        super_user.is_super = True

        mock_direct.return_value = {'success': True, 'message': '删除成功', 'requires_approval': False}

        result = await delete_order(mock_async_db, 1, super_user)

        assert result['success'] is True

    @pytest.mark.asyncio
    @patch('fastapi_app.services.order.commands._check_order_lock')
    async def test_delete_order_with_linked_return_blocked(self, mock_check_lock, mock_async_db):
        """有退货记录的订单不可删除：前置拒绝并说明原因（迁移 072 RESTRICT 的应用层前置）

        回归 2026-10-08：鲨鱼订单 68927 因 stock_return.stockout_id RESTRICT 外键，
        直删时 DB 抛 IntegrityError 被映射成含糊的 409；现应前置为带原因的 ValueError(→400)。
        """
        order = make_mock_order()
        # 2026-10-19 OCR 第三轮 H2 对齐 M4 重构后的调用序列——
        # ① select(Order.product_id) 无锁预读 ② 出库产品 distinct 集（空）
        # ③ get_product_for_update 产品行 ④ 加锁读订单行，⑤起是
        # assert_no_linked_returns 的关联退货查询（这里返回有退货，
        # 应在锁全链路之后被前置拒绝）。
        call_count = {'n': 0}

        async def _fake_execute(*_args, **_kwargs):
            call_count['n'] += 1
            if call_count['n'] == 1:
                return MagicMock(scalar_one_or_none=MagicMock(return_value=order.product_id))
            if call_count['n'] == 2:
                return MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))
            if call_count['n'] in (3, 4):
                return MagicMock(scalar_one_or_none=MagicMock(return_value=order))
            res = MagicMock()
            res.scalars.return_value.all.return_value = ['SR-20261006-0001']
            return res

        mock_async_db.execute = AsyncMock(side_effect=_fake_execute)

        super_user = MagicMock()
        super_user.id = 1
        super_user.is_super = True

        with pytest.raises(ValueError, match='退货记录'):
            await delete_order(mock_async_db, 1, super_user)


class TestCancelApproval:
    """审批取消"""

    @pytest.mark.asyncio
    async def test_cancel_approval_not_found(self, mock_async_db, mock_user):
        """取消不存在的审批"""
        # cancel_approval 自 2026-10-02 起用 select(...).with_for_update() 取审批行（原 db.get），
        # 与 approve/reject 同锁串行；mock 按新调用形状打桩。
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_async_db.execute = AsyncMock(return_value=result)

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
        result = MagicMock()
        result.scalar_one_or_none.return_value = approval
        mock_async_db.execute = AsyncMock(return_value=result)
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
    """湖北订单软删除过滤（只有 Order 有软删；StockIn 是硬删，无状态位）

    用真实 SQLite 执行 UNION 子查询，验证软删订单不出现在合并列表。
    StockIn.is_deleted 已于 2026-10-17 审计 Z03-R5 移除（死状态位，从未写入）。
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
    async def test_soft_deleted_order_excluded_from_unified_query(self, tmp_path):
        """软删 Order 不进合并子查询（既有行为的回归锚点）"""
        agen = self._session(tmp_path)
        sf, engine = await agen.__anext__()

        from sqlalchemy import select as sa_select

        from fastapi_app.services.order.beile import _build_beile_unified_query
        from fastapi_app.shared_models import Order, OrderItem, Product

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


class TestUnifiedRecordsKeyword:
    """订单+备货合并查询的 keyword OR 搜索（/customer-order 记录列表搜索框）

    用真实 SQLite 执行 unified 子查询：keyword 需同时 OR 匹配
    单号（订单号/备货号）、客户、产品名、条码 —— 任意命中即返回该行。
    """

    @staticmethod
    async def _session(tmp_path):
        """真实 SQLite 库（只建 union 涉及的表及其外键依赖，避开 JSONB 等 PG 专属列）"""
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from fastapi_app.shared_models import Base

        needed = {'order', 'order_item', 'stock_in', 'product', 'user'}
        tables = [t for t in Base.metadata.sorted_tables if t.name in needed]
        engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "unified.db"}')
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=tables)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        yield sf, engine

    @pytest.mark.asyncio
    async def test_keyword_matches_order_no_customer_product_barcode(self, tmp_path):
        """keyword 分别命中：订单号 / 客户名 / SKU 产品名 / SKU 条码 → 各返回对应订单行"""
        agen = self._session(tmp_path)
        sf, engine = await agen.__anext__()

        from sqlalchemy import select as sa_select

        from fastapi_app.services.order.unified import _build_unified_query
        from fastapi_app.shared_models import Order, OrderItem, Product

        async with sf() as db:
            p = Product(name='断桥铝窗框', barcode='6901234500116', factory='东莞')
            db.add(p)
            await db.flush()

            async def add_order(order_no, customer):
                o = Order(order_no=order_no, customer=customer, product_id=p.id, quantity=10)
                db.add(o)
                await db.flush()
                db.add(OrderItem(order_id=o.id, product_id=p.id,
                                 product_name=p.name, product_barcode=p.barcode, quantity=10))
                await db.flush()
                return o

            await add_order('DD-KW-NO', '无关客户甲')
            await add_order('DD-OTHER', '宏远建材')
            await add_order('DD-THIRD', '无关客户乙')
            await db.flush()

            for kw, expect_no in [('DD-KW-NO', 'DD-KW-NO'), ('宏远', 'DD-OTHER'), ('断桥铝', 'DD-KW-NO')]:
                subq = _build_unified_query(
                    record_type='all', keyword=kw,
                )
                rows = (await db.execute(sa_select(subq))).all()
                got = {r.order_no for r in rows if r.record_type == 'order'}
                assert expect_no in got, f'keyword={kw!r} 应命中 {expect_no}，实际 {got}'

            # 条码命中：三条订单共享同一 SKU 条码，应全部返回
            subq = _build_unified_query(record_type='all', keyword='6901234500116')
            rows = (await db.execute(sa_select(subq))).all()
            got = {r.order_no for r in rows if r.record_type == 'order'}
            assert got == {'DD-KW-NO', 'DD-OTHER', 'DD-THIRD'}, f'条码 keyword 应命中全部订单，实际 {got}'

        await engine.dispose()

    @pytest.mark.asyncio
    async def test_keyword_matches_stockin_no_customer_product(self, tmp_path):
        """keyword 命中备货侧：备货号 / 客户名 / 产品名 / 条码 → 返回备货行"""
        agen = self._session(tmp_path)
        sf, engine = await agen.__anext__()

        from sqlalchemy import select as sa_select

        from fastapi_app.services.order.unified import _build_unified_query
        from fastapi_app.shared_models import Product, StockIn

        async with sf() as db:
            p1 = Product(name='不锈钢合页', barcode='6901234500031', factory='东莞')
            p2 = Product(name='铝合金把手', barcode='6901234500049', factory='东莞')
            db.add_all([p1, p2])
            await db.flush()

            db.add(StockIn(stockin_no='BH-KW-001', customer='宏远建材', product_id=p1.id,
                           quantity=50, confirmed_at=None))
            db.add(StockIn(stockin_no='BH-OTHER', customer='无关客户', product_id=p2.id,
                           quantity=30, confirmed_at=None))
            await db.flush()

            # 备货号 / 客户名 / 产品名 / 条码 各自命中同一行
            for kw in ('BH-KW-001', '宏远', '不锈钢', '6901234500031'):
                subq = _build_unified_query(record_type='all', keyword=kw)
                rows = (await db.execute(sa_select(subq))).all()
                got = {r.order_no for r in rows if r.record_type == 'stockin'}
                assert got == {'BH-KW-001'}, f'keyword={kw!r} 应只命中 BH-KW-001，实际 {got}'

        await engine.dispose()

    @pytest.mark.asyncio
    async def test_keyword_none_returns_all(self, tmp_path):
        """keyword=None（搜索框为空）不做任何过滤，与既有行为一致"""
        agen = self._session(tmp_path)
        sf, engine = await agen.__anext__()

        from sqlalchemy import select as sa_select

        from fastapi_app.services.order.unified import _build_unified_query
        from fastapi_app.shared_models import Order, OrderItem, Product, StockIn

        async with sf() as db:
            p = Product(name='全部测试品', barcode='6909999999999', factory='东莞')
            db.add(p)
            await db.flush()

            o = Order(order_no='DD-ALL', customer='客户丙', product_id=p.id, quantity=5)
            db.add(o)
            await db.flush()
            db.add(OrderItem(order_id=o.id, product_id=p.id,
                             product_name=p.name, product_barcode=p.barcode, quantity=5))
            db.add(StockIn(stockin_no='BH-ALL', customer='客户丙', product_id=p.id,
                           quantity=7, confirmed_at=None))
            await db.flush()

            subq = _build_unified_query(record_type='all', keyword=None)
            rows = (await db.execute(sa_select(subq))).all()
            types = {r.record_type for r in rows}
            assert types == {'order', 'stockin'}, f'无 keyword 应返回订单+备货，实际 {types}'

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
