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


async def test_rename_process_to_duplicate_returns_client_error_with_message(
    async_client, auth_headers, async_db_session,
):
    """回归（hubei-M-4）：改工序名撞同 SKU 已有工序名，不得 500。

    旧实现：服务层直接赋值 → flush 撞唯一索引 uq_oosp_order_item_product_process
    （NULLS NOT DISTINCT）→ IntegrityError 走默认映射 → 500「数据库操作失败」。
    修复后：服务层预检抛 ValueError → 400 +「该 SKU 已存在同名工序」；
    预检通过后并发抢先插入的毫秒级窗口由端点 error_map 把 IntegrityError
    兜底映射为 409 同文案（与预设端点口径一致）。
    """
    product, order, _ = await _seed_order(async_db_session)
    first = await _generate_single_process(async_client, auth_headers, product, order)
    second = await _generate_single_process(async_client, auth_headers, product, order, "转印")
    assert first != second

    resp = await async_client.put(
        f"{PREFIX}/processes/{second}",
        json={"process_type": "电绣"},
        headers=auth_headers,
    )
    assert resp.status_code == 400, f"撞名改名旧实现是 500：HTTP {resp.status_code} {resp.text}"
    assert resp.json()["detail"] == "该 SKU 已存在同名工序"


async def test_concurrent_receive_shipment_keeps_item_quantity(test_engine):
    """回归（hubei-M-2）：并发双收同一发货单，不得把已收明细「收货数量」清零。

    两个独立连接真实复现（非 mock）：T1、T2 同时确认同一张 status=shipped 的发货单。
    修复前 T2 用普通 SELECT 在 T1 未提交前读到 status=shipped → 通过状态检查 →
    在工序行锁上等 T1 提交后 remaining=0 → receive_order_process 返回 None →
    T2 把明细 received_quantity 覆盖为 0 并再次置 status=received；
    修复后 T2 的 shipment 读取带行锁（with_for_update），在 T1 提交后重读
    status=received → 幂等早退 already_received=True，明细保持 T1 写入的值。
    """
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from fastapi_app.services.outsource._shipments import create_shipment, receive_shipment
    from fastapi_app.shared_models import OutsourceShipmentItem

    maker = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False,
    )

    # 种子：订单 + 工序 + 发货单（发货 5 件，走真实 create_shipment 路径）
    async with maker() as s0:
        product, order, item = await _seed_order(s0)
        p = OrderOutsourceProcess(
            order_id=order.id, order_item_id=item.id, product_id=product.id,
            product_name=product.name, process_type="电绣", sort_order=0, status="pending",
        )
        s0.add(p)
        await s0.flush()
        shipment = await create_shipment(s0, order.id, [(p.id, 5)], username="shipper")
        process_id, shipment_id = p.id, shipment["id"]
        await s0.commit()

    async def _t1():
        async with maker() as s:
            async with s.begin():
                res = await receive_shipment(s, shipment_id, username="beile-t1")
                # 持锁不提交，给 T2 留出「读到旧快照」的窗口
                await asyncio.sleep(0.6)
                return res

    async def _t2():
        # 错峰启动：确保 T2 的首次读取落在 T1 已持有行锁、尚未提交的窗口内
        await asyncio.sleep(0.15)
        async with maker() as s:
            async with s.begin():
                return await receive_shipment(s, shipment_id, username="beile-t2")

    r1, r2 = await asyncio.gather(_t1(), _t2())

    assert r1["success"] is True and r1["already_received"] is False
    assert r2["success"] is True
    assert r2["already_received"] is True, f"T2 应幂等早退而不是把明细清零：{r2}"

    async with maker() as s:
        ship_item = (await s.execute(
            select(OutsourceShipmentItem).where(OutsourceShipmentItem.shipment_id == shipment_id)
        )).scalars().one()
        proc = (await s.execute(
            select(OrderOutsourceProcess).where(OrderOutsourceProcess.id == process_id)
        )).scalar_one()
    assert (ship_item.received_quantity or 0) == 5, (
        f"并发双收不得覆盖明细收货数量（应保持 T1 写入的 5），实际 {ship_item.received_quantity}"
    )
    assert (proc.received_quantity or 0) == 5
