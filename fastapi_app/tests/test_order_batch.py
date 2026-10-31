"""订单批次号管理 - 单元测试"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.services import order_batch_service
from fastapi_app.shared_models import Order, User


@pytest.fixture
def mock_user():
    user = MagicMock(spec=User)
    user.id = 1
    user.username = "admin"
    return user


@pytest.fixture
def mock_order():
    order = MagicMock(spec=Order)
    order.id = 1
    order.order_no = "PO-001"
    order.customer = "MINISO国内"
    order.product_id = 1
    order.quantity = 100
    order.status = "已出货"
    order.batch_no = "BATCH-001"
    order.batch_completed_at = None
    order.batch_completed_by_id = None
    order.is_deleted = False
    product = MagicMock()
    product.name = "测试产品"
    order.product = product
    order.can_transition_to = MagicMock(return_value=True)  # legacy mock, no longer used in production
    return order


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    return db


class TestWhitelist:
    @pytest.mark.asyncio
    async def test_get_whitelist_from_db(self, mock_db):
        mock_scalar = MagicMock()
        mock_scalar.scalar_one_or_none.return_value = json.dumps(["MINISO国际", "MINISO国内", "MINISO电商", "MINISO小程序"])
        mock_db.execute.return_value = mock_scalar

        with patch.object(order_batch_service, '_get_redis_client', return_value=None):
            result = await order_batch_service.get_whitelist(mock_db)

        assert result == ["MINISO国际", "MINISO国内", "MINISO电商", "MINISO小程序"]

    @pytest.mark.asyncio
    async def test_is_whitelisted_true(self, mock_db):
        with patch.object(order_batch_service, 'get_whitelist', return_value=["MINISO国内", "MINISO国际"]):
            result = await order_batch_service.is_whitelisted(mock_db, "MINISO国内")
        assert result is True

    @pytest.mark.asyncio
    async def test_is_whitelisted_false(self, mock_db):
        with patch.object(order_batch_service, 'get_whitelist', return_value=["MINISO国内"]):
            result = await order_batch_service.is_whitelisted(mock_db, "其他客户")
        assert result is False


class TestGetBatchOrders:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_whitelist(self, mock_db):
        with patch.object(order_batch_service, 'get_whitelist', return_value=[]):
            result = await order_batch_service.get_batch_orders(mock_db)
        assert result == {'items': [], 'total': 0}

    @pytest.mark.asyncio
    async def test_filters_by_whitelist_customers(self, mock_db):
        with patch.object(order_batch_service, 'get_whitelist', return_value=["MINISO国内"]):
            mock_scalar = MagicMock()
            mock_scalar.scalar.return_value = 0
            mock_db.execute.return_value = mock_scalar
            result = await order_batch_service.get_batch_orders(mock_db)
        assert result['total'] == 0


class TestBatchAssign:
    @pytest.mark.asyncio
    async def test_rejects_non_whitelisted_customer(self, mock_db, mock_user):
        order = MagicMock(spec=Order)
        order.id = 1
        order.customer = "非白名单客户"
        order.is_deleted = False

        mock_scalar = MagicMock()
        mock_scalar.scalars.return_value.all.return_value = [order]
        mock_db.execute.return_value = mock_scalar

        with patch.object(order_batch_service, 'get_whitelist', return_value=["MINISO国内"]):
            with pytest.raises(ValueError, match="不在白名单中"):
                await order_batch_service.batch_assign(mock_db, order_ids=[1], batch_no="BATCH-001", user=mock_user)

    @pytest.mark.asyncio
    async def test_batch_assign_success(self, mock_db, mock_user):
        order = MagicMock(spec=Order)
        order.id = 1
        order.customer = "MINISO国内"
        order.is_deleted = False

        mock_scalar = MagicMock()
        mock_scalar.scalars.return_value.all.return_value = [order]
        mock_db.execute.return_value = mock_scalar

        with patch.object(order_batch_service, 'get_whitelist', return_value=["MINISO国内"]):
            with patch.object(order_batch_service, '_safe_publish_event', new_callable=AsyncMock):
                result = await order_batch_service.batch_assign(mock_db, order_ids=[1], batch_no="BATCH-001", user=mock_user)

        assert result['updated_count'] == 1
        assert order.batch_no == "BATCH-001"


class TestCompleteBatch:
    @pytest.mark.asyncio
    async def test_raises_on_empty_batch(self, mock_db, mock_user):
        mock_scalar = MagicMock()
        mock_scalar.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_scalar

        with pytest.raises(ValueError, match="没有可完成的记录"):
            await order_batch_service.complete_batch(mock_db, batch_no="EMPTY", user=mock_user)

    @pytest.mark.asyncio
    async def test_completes_valid_orders(self, mock_db, mock_user, mock_order):
        mock_scalar = MagicMock()
        mock_scalar.scalars.return_value.all.return_value = [mock_order]
        mock_db.execute.return_value = mock_scalar

        with patch.object(order_batch_service, '_safe_publish_event', new_callable=AsyncMock):
            with patch(
                'fastapi_app.services.order_utils.compute_order_statuses_batch',
                new_callable=AsyncMock, return_value={1: '批次已完成'},
            ) as m_batch:
                result = await order_batch_service.complete_batch(mock_db, batch_no="BATCH-001", user=mock_user)

        assert result['completed_count'] == 1
        assert result['failed_orders'] == []
        assert mock_order.status == "批次已完成"
        # A-M13：N 张单只允许一次聚合计算，不能退回逐单 2 条 SQL
        assert m_batch.await_count == 1

    @pytest.mark.asyncio
    async def test_status_computed_once_for_whole_batch(self, mock_db, mock_user):
        """多张已出货订单共用一次批量状态计算（A-M13 回归）。"""
        orders = []
        for oid in (1, 2, 3):
            o = MagicMock(spec=Order)
            o.id = oid
            o.order_no = f"PO-00{oid}"
            o.status = "已出货"
            o.can_transition_to = MagicMock(return_value=True)
            orders.append(o)

        mock_scalar = MagicMock()
        mock_scalar.scalars.return_value.all.return_value = orders
        mock_db.execute.return_value = mock_scalar

        with patch.object(order_batch_service, '_safe_publish_event', new_callable=AsyncMock):
            with patch(
                'fastapi_app.services.order_utils.compute_order_statuses_batch',
                new_callable=AsyncMock,
                return_value={1: '批次已完成', 2: '批次已完成', 3: '批次已完成'},
            ) as m_batch:
                result = await order_batch_service.complete_batch(mock_db, batch_no="BATCH-001", user=mock_user)

        assert result['completed_count'] == 3
        assert m_batch.await_count == 1
        assert len(m_batch.await_args.args[1]) == 3
        assert all(o.status == '批次已完成' for o in orders)

    @pytest.mark.asyncio
    async def test_collects_failed_orders(self, mock_db, mock_user):
        order = MagicMock(spec=Order)
        order.id = 1
        order.order_no = "PO-001"
        order.status = "待备货"
        order.batch_no = "BATCH-001"
        order.can_transition_to = MagicMock(return_value=False)

        mock_scalar = MagicMock()
        mock_scalar.scalars.return_value.all.return_value = [order]
        mock_db.execute.return_value = mock_scalar

        with patch.object(order_batch_service, '_safe_publish_event', new_callable=AsyncMock):
            result = await order_batch_service.complete_batch(mock_db, batch_no="BATCH-001", user=mock_user)

        assert result['completed_count'] == 0
        assert len(result['failed_orders']) == 1
        assert result['failed_orders'][0]['order_no'] == "PO-001"


def _result(**kwargs):
    result = MagicMock()
    for name, value in kwargs.items():
        setattr(result, name, value)
    return result


def _lock_result(orders):
    result = MagicMock()
    result.scalars.return_value.all.return_value = orders
    return result


class TestUpdateBatchNo:
    @pytest.mark.asyncio
    async def test_raises_on_nonexistent_order(self, mock_db, mock_user):
        snapshot = MagicMock()
        snapshot.first.return_value = None
        mock_db.execute.return_value = snapshot

        with pytest.raises(ValueError, match="订单不存在"):
            await order_batch_service.update_batch_no(mock_db, order_id=999, batch_no="X", sync_same_batch=False, user=mock_user)

    @pytest.mark.asyncio
    async def test_updates_single_order(self, mock_db, mock_user, mock_order):
        snapshot = MagicMock()
        snapshot.first.return_value = MagicMock(id=1, batch_no="BATCH-001")
        mock_db.execute.side_effect = [snapshot, _lock_result([mock_order])]

        with patch.object(order_batch_service, 'is_whitelisted', return_value=True):
            with patch.object(order_batch_service, '_safe_publish_event', new_callable=AsyncMock):
                result = await order_batch_service.update_batch_no(mock_db, order_id=1, batch_no="NEW-BATCH", sync_same_batch=False, user=mock_user)

        assert result['updated_count'] == 1
        assert mock_order.batch_no == "NEW-BATCH"

    @pytest.mark.asyncio
    async def test_sync_locks_target_and_mates_in_one_ascending_statement(self, mock_db, mock_user):
        """P1-3：目标与同批订单必须在同一条 FOR UPDATE 且按 id 升序锁定。"""
        target = MagicMock(spec=Order)
        target.id = 5
        target.batch_no = "B1"
        mate = MagicMock(spec=Order)
        mate.id = 3
        mate.batch_no = "B1"

        snapshot = MagicMock()
        snapshot.first.return_value = MagicMock(id=5, batch_no="B1")
        sync_result = MagicMock(rowcount=2)
        mock_db.execute.side_effect = [snapshot, _lock_result([mate, target]), sync_result]

        with patch.object(order_batch_service, '_safe_publish_event', new_callable=AsyncMock):
            result = await order_batch_service.update_batch_no(
                mock_db, order_id=5, batch_no="B2", sync_same_batch=True, user=mock_user,
            )

        assert result['updated_count'] == 2
        assert target.batch_no == "B2"

        lock_stmt = mock_db.execute.await_args_list[1].args[0]
        sql = str(lock_stmt.compile(compile_kwargs={'literal_binds': True}))
        assert 'FOR UPDATE' in sql
        assert 'ORDER BY "order".id' in sql
        # 目标行与同批过滤条件在同一条语句里（旧实现是「先锁目标，再锁同批」两条）
        assert '"order".id = 5' in sql
        assert "batch_no = 'B1'" in sql

        sync_stmt = mock_db.execute.await_args_list[2].args[0]
        sync_params = sync_stmt.compile().params.values()
        assert [3] in sync_params  # 只批量更新同批订单（目标行走实例赋值）
        assert "B2" in sync_params

    @pytest.mark.asyncio
    async def test_sync_aborts_when_batch_changed_before_lock(self, mock_db, mock_user):
        """并发改过批次号时不得按过期集合同步，返回 409 让用户重试。"""
        target = MagicMock(spec=Order)
        target.id = 5
        target.batch_no = "B2"  # 拿到锁时已不是快照里的 B1

        snapshot = MagicMock()
        snapshot.first.return_value = MagicMock(id=5, batch_no="B1")
        mock_db.execute.side_effect = [snapshot, _lock_result([target])]

        with pytest.raises(order_batch_service.ConflictError, match="并发修改"):
            await order_batch_service.update_batch_no(
                mock_db, order_id=5, batch_no="B3", sync_same_batch=True, user=mock_user,
            )
