"""外发 HTTP 主链：生成、分批收发、批量原子回滚、权限和发货单闭环。"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from fastapi_app.core.deps import _get_user_with_permissions
from fastapi_app.main import app
from fastapi_app.shared_models import (
    Order,
    OrderItem,
    OrderOutsourceProcess,
    Product,
    User,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]
PREFIX = "/api/v1/outsource"


async def _seed_order(db, *, factory: str = "湖北"):
    tag = uuid4().hex[:8]
    product = Product(
        name=f"外发产品-{tag}", barcode=f"OUT-{tag}", factory=factory,
        current_stock=0, initial_stock=0,
    )
    db.add(product)
    await db.flush()
    order = Order(
        order_no=f"OUT-{tag}"[:20],
        customer=f"外发客户-{tag}",
        product_id=product.id,
        quantity=10,
        status="待备货",
        order_date=datetime.now(UTC),
    )
    db.add(order)
    await db.flush()
    item = OrderItem(
        order_id=order.id,
        product_id=product.id,
        product_name=product.name,
        product_barcode=product.barcode,
        quantity=10,
    )
    db.add(item)
    await db.flush()
    return product, order, item


async def _generate_single_process(client, headers, product, order, name="电绣"):
    preset = await client.post(
        f"{PREFIX}/process-types",
        json={"product_id": product.id, "process_type": name, "sort_order": 0},
        headers=headers,
    )
    assert preset.status_code == 200, preset.text
    generated = await client.post(
        f"{PREFIX}/orders/{order.id}/processes/generate", headers=headers,
    )
    assert generated.status_code == 200, generated.text
    listed = await client.get(f"{PREFIX}/orders/{order.id}/processes", headers=headers)
    assert listed.status_code == 200
    return next(row["id"] for row in listed.json()["data"] if row["process_type"] == name)


async def test_outsource_http_generate_batch_rollback_and_partial_receive(
    async_client, auth_headers, async_db_session
):
    product, order, _ = await _seed_order(async_db_session)
    first_process = await _generate_single_process(async_client, auth_headers, product, order)
    second_process = await _generate_single_process(
        async_client, auth_headers, product, order, "转印",
    )
    order_id = order.id

    # 批量发货：第一条合法、第二条不存在，整批必须回滚。
    rollback = await async_client.post(
        f"{PREFIX}/orders/{order_id}/processes/ship-batch",
        json={"items": [
            {"process_id": first_process, "quantity": 1},
            {"process_id": 99999999, "quantity": 1},
        ]},
        headers=auth_headers,
    )
    assert rollback.status_code == 400
    rows = list((await async_db_session.execute(
        select(OrderOutsourceProcess).where(OrderOutsourceProcess.order_id == order_id)
    )).scalars().all())
    assert {(row.id, row.shipped_quantity or 0, row.status) for row in rows} == {
        (first_process, 0, "pending"), (second_process, 0, "pending"),
    }

    shipped = await async_client.post(
        f"{PREFIX}/processes/{first_process}/ship",
        json={"shipped_quantity": 4}, headers=auth_headers,
    )
    assert shipped.status_code == 200
    assert shipped.json()["data"][0]["status"] == "shipped"
    received = await async_client.post(
        f"{PREFIX}/processes/{first_process}/receive",
        json={"received_quantity": 2}, headers=auth_headers,
    )
    assert received.status_code == 200
    assert received.json()["data"][0]["status"] == "shipped"
    again = await async_client.post(
        f"{PREFIX}/processes/{first_process}/ship",
        json={"shipped_quantity": 6}, headers=auth_headers,
    )
    assert again.status_code == 200
    final_receive = await async_client.post(
        f"{PREFIX}/processes/{first_process}/receive", headers=auth_headers,
    )
    assert final_receive.status_code == 200
    assert final_receive.json()["data"][0]["status"] == "received"
    over = await async_client.post(
        f"{PREFIX}/processes/{first_process}/ship",
        json={"shipped_quantity": 1}, headers=auth_headers,
    )
    assert over.status_code == 400


async def test_outsource_permission_and_shipment_receive_flow(
    async_client, auth_headers, async_db_session
):
    product, order, _ = await _seed_order(async_db_session)
    process_id = await _generate_single_process(async_client, auth_headers, product, order)

    shipment = await async_client.post(
        f"{PREFIX}/shipments",
        json={"order_id": order.id, "items": [
            {"process_id": process_id, "quantity": 3},
        ]},
        headers=auth_headers,
    )
    assert shipment.status_code == 200, shipment.text
    shipment_id = shipment.json()["id"]
    received = await async_client.post(
        f"{PREFIX}/shipments/{shipment_id}/receive", headers=auth_headers,
    )
    assert received.status_code == 200, received.text
    detail = await async_client.get(f"{PREFIX}/shipments/{shipment_id}", headers=auth_headers)
    assert detail.status_code == 200
    assert detail.json()["status"] == "received"
    repeated = await async_client.post(
        f"{PREFIX}/shipments/{shipment_id}/receive", headers=auth_headers,
    )
    assert repeated.status_code == 200
    assert repeated.json()["already_received"] is True

    non_manage = User(username="no-outsource", password="x", is_super=False, status=True)
    non_manage.permissions = []

    async def override_user():
        return non_manage

    app.dependency_overrides[_get_user_with_permissions] = override_user
    try:
        denied = await async_client.post(
            f"{PREFIX}/process-types",
            json={"product_id": product.id, "process_type": "无权工序"},
            headers=auth_headers,
        )
    finally:
        app.dependency_overrides.pop(_get_user_with_permissions, None)
    assert denied.status_code == 403
