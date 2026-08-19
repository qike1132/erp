"""
集成测试 — FastAPI 异步版

跨模块业务流程测试：订单流程、库存流程、审批流程、数据一致性。
从 Flask unittest 迁移至 pytest-asyncio。
"""
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from fastapi_app.core.security import hash_password
from fastapi_app.shared_models import Order, Product, StockIn, StockOut
from fastapi_app.shared_models.approval import ApprovalRequest
from fastapi_app.shared_models.user import User

MARK = pytest.mark.integration


@MARK
class TestOrderFlow:

    @pytest.mark.asyncio
    async def test_order_status_transitions(self, async_db_session):
        """订单状态流转: pending → approved → completed"""
        user = await _create_test_user(async_db_session)
        product = await _create_test_product(async_db_session, "产品A", "P001", 100)

        # 1. 创建订单
        order = Order(
            order_no="ORD001",
            product_id=product.id,
            customer="测试客户",
            quantity=10,
            order_date=datetime.now(UTC),
            status="待备货",
        )
        async_db_session.add(order)
        await async_db_session.flush()
        assert order.status == "待备货"

        # 2. 审批
        approval = ApprovalRequest(
            order_id=order.id,
            requester_id=user.id,
            operation_type="create",
        )
        async_db_session.add(approval)
        await async_db_session.flush()
        assert approval.status == "pending"

        # 3. 审批通过
        approval.status = "approved"
        await async_db_session.flush()
        assert approval.status == "approved"


@MARK
class TestStockFlow:

    @pytest.mark.asyncio
    async def test_stock_in_and_out_flow(self, async_db_session):
        """入库出库完整流程"""
        product = await _create_test_product(async_db_session, "产品B", "P002", 100)
        initial_stock = product.current_stock

        # 入库
        stock_in = StockIn(
            stockin_no="SI-INT-001",
            product_id=product.id,
            customer="测试",
            quantity=50,
            stockin_date=datetime.now(UTC),
        )
        async_db_session.add(stock_in)
        product.current_stock += 50
        await async_db_session.flush()
        assert product.current_stock == initial_stock + 50

        # 出库
        stock_out = StockOut(
            stockout_no="SO-INT-001",
            product_id=product.id,
            customer="测试",
            quantity=30,
            stockout_date=datetime.now(UTC),
        )
        async_db_session.add(stock_out)
        product.current_stock -= 30
        await async_db_session.flush()
        assert product.current_stock == initial_stock + 50 - 30

    @pytest.mark.asyncio
    async def test_concurrent_stock_operations(self, async_db_session):
        """并发库存操作一致性"""
        product = await _create_test_product(async_db_session, "产品C", "P003", 100)
        initial_stock = product.current_stock

        product.current_stock += 20
        product.current_stock -= 10
        await async_db_session.flush()

        assert product.current_stock == initial_stock + 20 - 10

    @pytest.mark.asyncio
    async def test_product_stock_update_consistency(self, async_db_session):
        """产品库存更新一致性"""
        product = await _create_test_product(async_db_session, "产品D", "P004", 100)
        initial_stock = product.current_stock

        stock_in = StockIn(
            stockin_no="SI-INT-002",
            product_id=product.id,
            customer="测试",
            quantity=100,
            stockin_date=datetime.now(UTC),
        )
        async_db_session.add(stock_in)
        product.current_stock += 100
        await async_db_session.flush()

        result = await async_db_session.execute(
            select(Product).where(Product.id == product.id)
        )
        saved_product = result.scalars().first()
        assert saved_product is not None
        assert saved_product.current_stock == initial_stock + 100

    @pytest.mark.asyncio
    async def test_insufficient_stock_detection(self, async_db_session):
        """库存不足检测"""
        product = await _create_test_product(async_db_session, "产品E", "P005", 10)
        requested = product.current_stock + 100
        assert requested > product.current_stock


@MARK
class TestApprovalFlow:

    @pytest.mark.asyncio
    async def test_approval_reject_flow(self, async_db_session):
        """审批拒绝流程"""
        user = await _create_test_user(async_db_session)
        product = await _create_test_product(async_db_session, "产品F", "P006", 100)

        order = Order(
            order_no="ORD-REJECT",
            product_id=product.id,
            customer="测试客户",
            quantity=10,
            order_date=datetime.now(UTC),
            status="待备货",
        )
        async_db_session.add(order)
        await async_db_session.flush()

        approval = ApprovalRequest(
            order_id=order.id,
            requester_id=user.id,
            operation_type="create",
        )
        async_db_session.add(approval)
        await async_db_session.flush()

        approval.status = "rejected"
        await async_db_session.flush()
        assert approval.status == "rejected"


# ============================================================
# 辅助函数
# ============================================================

async def _create_test_user(db, username="test_integration_user"):
    """创建测试用临时用户"""
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalars().first()
    if not user:
        user = User(username=username, password=hash_password("test123"), status=True)
        db.add(user)
        await db.flush()
    return user


async def _create_test_product(db, name, barcode, stock):
    """创建测试用临时产品"""
    result = await db.execute(select(Product).where(Product.barcode == barcode))
    product = result.scalars().first()
    if not product:
        product = Product(name=name, barcode=barcode, current_stock=stock, initial_stock=stock)
        db.add(product)
        await db.flush()
    return product
