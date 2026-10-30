"""审批 HTTP 闭环、权限门与真实并发终态。"""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fastapi_app.core.deps import _get_user_with_permissions
from fastapi_app.core.exceptions import db_transaction
from fastapi_app.main import app
from fastapi_app.services import approval_service, order_service
from fastapi_app.shared_models import ApprovalRequest, Order, OrderItem, User

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def _seed_edit_request(db, product, requester_id: int, *, quantity: int = 100):
    tag = uuid4().hex[:8]
    order = Order(
        order_no=f"APR-{tag}"[:20],
        customer=f"审批客户-{tag}",
        product_id=product.id,
        quantity=10,
        status="待备货",
        order_date=datetime.now(UTC),
        is_locked=True,
        locked_by_id=requester_id,
    )
    db.add(order)
    await db.flush()
    db.add(OrderItem(
        order_id=order.id,
        product_id=product.id,
        product_name=product.name,
        product_barcode=product.barcode,
        quantity=10,
    ))
    approval = ApprovalRequest(
        order_id=order.id,
        requester_id=requester_id,
        operation_type=ApprovalRequest.OPERATION_EDIT,
        operation_data=json.dumps({
            "quantity": quantity,
            "customer": f"审批后客户-{tag}",
            "note": "审批闭环",
        }, ensure_ascii=False),
        status=ApprovalRequest.STATUS_PENDING,
        lock_time=datetime.now(UTC).replace(tzinfo=None),
    )
    db.add(approval)
    await db.flush()
    # 端点事务失败会 rollback 共享测试会话；先提交种子，避免被一并回滚。
    await db.commit()
    return order, approval


async def test_approve_edit_updates_order_and_is_not_repeatable(
    async_client, auth_headers, async_db_session, admin_user, normal_user, test_product
):
    order, approval = await _seed_edit_request(
        async_db_session, test_product, normal_user.id,
    )
    approval_id = approval.id

    response = await async_client.post(
        f"/api/v1/approvals/approve/{approval_id}", headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    await async_db_session.refresh(order)
    await async_db_session.refresh(approval)
    assert approval.status == ApprovalRequest.STATUS_APPROVED
    assert approval.approver_id == admin_user.id
    assert order.quantity == 100
    assert order.customer.startswith("审批后客户-")

    repeated = await async_client.post(
        f"/api/v1/approvals/approve/{approval_id}", headers=auth_headers,
    )
    assert repeated.status_code == 400


async def test_approval_endpoints_are_superuser_only(
    async_client, auth_headers, async_db_session, normal_user, test_product
):
    _, approval = await _seed_edit_request(async_db_session, test_product, normal_user.id)
    non_super = User(username="non-super-approver", password="x", is_super=False, status=True)
    non_super.permissions = []

    async def override_user():
        return non_super

    app.dependency_overrides[_get_user_with_permissions] = override_user
    try:
        response = await async_client.post(
            f"/api/v1/approvals/approve/{approval.id}", headers=auth_headers,
        )
    finally:
        app.dependency_overrides.pop(_get_user_with_permissions, None)
    assert response.status_code == 403


async def test_superuser_cannot_approve_own_request(
    async_client, auth_headers, async_db_session, admin_user, test_product
):
    _, approval = await _seed_edit_request(async_db_session, test_product, admin_user.id)
    approval_id = approval.id
    response = await async_client.post(
        f"/api/v1/approvals/approve/{approval_id}", headers=auth_headers,
    )
    assert response.status_code == 400
    assert "不能审批自己" in response.json()["detail"]
    status = await async_db_session.scalar(
        select(ApprovalRequest.status).where(ApprovalRequest.id == approval_id)
    )
    assert status == ApprovalRequest.STATUS_PENDING


async def test_concurrent_approve_and_cancel_have_one_terminal_state(
    async_db_session, test_engine, admin_user, normal_user, test_product
):
    order, approval = await _seed_edit_request(
        async_db_session, test_product, normal_user.id, quantity=66,
    )
    approval_id = approval.id
    order_id = order.id
    await async_db_session.commit()
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async def approve():
        async with factory() as session:
            try:
                async with db_transaction(session):
                    await approval_service.approve_request(session, approval_id, admin_user)
                return True
            except (ValueError, HTTPException):
                await session.rollback()
                return False

    async def cancel():
        async with factory() as session:
            try:
                async with db_transaction(session):
                    await order_service.cancel_approval(session, approval_id, normal_user)
                return True
            except (ValueError, HTTPException):
                await session.rollback()
                return False

    approved, cancelled = await asyncio.gather(approve(), cancel())
    assert {approved, cancelled} == {True, False}

    async with factory() as check:
        final_approval = await check.scalar(
            select(ApprovalRequest).where(ApprovalRequest.id == approval_id)
        )
        final_order = await check.get(Order, order_id)
    assert final_approval.status in {
        ApprovalRequest.STATUS_APPROVED, ApprovalRequest.STATUS_CANCELLED,
    }
    assert final_approval.status != ApprovalRequest.STATUS_PENDING
    if final_approval.status == ApprovalRequest.STATUS_APPROVED:
        assert final_order.quantity == 66
    else:
        assert final_order.quantity == 10
