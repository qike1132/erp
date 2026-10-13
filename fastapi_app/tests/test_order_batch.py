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
            with patch('fastapi_app.services.order_utils.compute_order_status_from_db', new_callable=AsyncMock, return_value='批次已完成'):
                result = await order_batch_service.complete_batch(mock_db, batch_no="BATCH-001", user=mock_user)

        assert result['completed_count'] == 1
        assert result['failed_orders'] == []
        assert mock_order.status == "批次已完成"

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


class TestUpdateBatchNo:
    @pytest.mark.asyncio
    async def test_raises_on_nonexistent_order(self, mock_db, mock_user):
        mock_scalar = MagicMock()
        mock_scalar.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_scalar

        with pytest.raises(ValueError, match="订单不存在"):
            await order_batch_service.update_batch_no(mock_db, order_id=999, batch_no="X", sync_same_batch=False, user=mock_user)

    @pytest.mark.asyncio
    async def test_updates_single_order(self, mock_db, mock_user, mock_order):
        mock_scalar = MagicMock()
        mock_scalar.scalar_one_or_none.return_value = mock_order
        mock_db.execute.return_value = mock_scalar

        with patch.object(order_batch_service, 'is_whitelisted', return_value=True):
            with patch.object(order_batch_service, '_safe_publish_event', new_callable=AsyncMock):
                result = await order_batch_service.update_batch_no(mock_db, order_id=1, batch_no="NEW-BATCH", sync_same_batch=False, user=mock_user)

        assert result['updated_count'] == 1
        assert mock_order.batch_no == "NEW-BATCH"
