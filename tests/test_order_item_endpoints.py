"""单 SKU 级订单明细端点（PUT /orders/items/{id}）回归测试。

覆盖：
- 编辑单个 SKU 后 order.quantity = Σ items.quantity（兼容值重算，见 order_batch_create.py:199）
- 删除非末项保留订单、删除末项等价删整单、已抵扣 SKU 拒删（Task 2 追加）
"""
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio

from fastapi_app.shared_models.order import Order
from fastapi_app.shared_models.order_item import OrderItem


@pytest_asyncio.fixture
async def seeded_multi_sku_order(async_db_session, test_products, test_customer):
    """1 张订单、2 个 SKU（qty 100 / 200）。每次调用用唯一单号，避免跨用例污染。"""
    order = Order(
        order_no=f"SO-MSKU-{uuid.uuid4().hex[:8]}",
        product_id=test_products[0].id,
        customer=test_customer.name,
        quantity=300,
        order_date=datetime.now(UTC),
        status="待备货",
    )
    async_db_session.add(order)
    await async_db_session.flush()
    it1 = OrderItem(
        order_id=order.id, product_id=test_products[0].id, quantity=100,
        product_name=test_products[0].name, product_barcode=test_products[0].barcode,
    )
    it2 = OrderItem(
        order_id=order.id, product_id=test_products[1].id, quantity=200,
        product_name=test_products[1].name, product_barcode=test_products[1].barcode,
    )
    async_db_session.add_all([it1, it2])
    await async_db_session.flush()
    return order.id, [it1.id, it2.id]


@pytest.mark.asyncio
async def test_update_item_recomputes_order_quantity(
    async_client, seeded_multi_sku_order, auth_headers,
):
    """改一个 SKU 的数量后，order.quantity 必须 = Σ items.quantity（100→150，+200=350）。"""
    order_id, item_ids = seeded_multi_sku_order
    resp = await async_client.put(
        f"/api/v1/orders/items/{item_ids[0]}", json={"quantity": 150}, headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    detail = await async_client.get(f"/api/v1/orders/{order_id}", headers=auth_headers)
    # 手算字面量：150 + 200
    assert detail.json()["quantity"] == 350


@pytest_asyncio.fixture
async def seeded_single_item_order(async_db_session, test_products, test_customer):
    """1 张订单、1 个 SKU。返回 (order_id, item_id)。"""
    order = Order(
        order_no=f"SO-SINGLE-{uuid.uuid4().hex[:8]}",
        product_id=test_products[0].id,
        customer=test_customer.name,
        quantity=100,
        order_date=datetime.now(UTC),
        status="待备货",
    )
    async_db_session.add(order)
    await async_db_session.flush()
    it = OrderItem(
        order_id=order.id, product_id=test_products[0].id, quantity=100,
        product_name=test_products[0].name, product_barcode=test_products[0].barcode,
    )
    async_db_session.add(it)
    await async_db_session.flush()
    return order.id, it.id


@pytest_asyncio.fixture
async def seeded_deducted_item(async_db_session, test_products, test_customer, test_stockin):
    """1 张订单、1 个 SKU，且该 SKU 已被备货抵扣（stockin_id 非空的出货）。返回 item_id。"""
    from fastapi_app.shared_models.stock_out import StockOut

    order = Order(
        order_no=f"SO-DED-{uuid.uuid4().hex[:8]}",
        product_id=test_products[0].id,
        customer=test_customer.name,
        quantity=100,
        order_date=datetime.now(UTC),
        status="待备货",
    )
    async_db_session.add(order)
    await async_db_session.flush()
    it = OrderItem(
        order_id=order.id, product_id=test_products[0].id, quantity=100,
        product_name=test_products[0].name, product_barcode=test_products[0].barcode,
    )
    async_db_session.add(it)
    await async_db_session.flush()
    async_db_session.add(StockOut(
        stockout_no=f"SO-DEDOUT-{uuid.uuid4().hex[:8]}",
        product_id=test_products[0].id, customer=test_customer.name,
        quantity=40, returned_quantity=0, stockout_date=datetime.now(UTC),
        order_id=order.id, stockin_id=test_stockin.id,   # stockin_id 非空 = 抵扣
    ))
    await async_db_session.flush()
    return it.id


@pytest.mark.asyncio
async def test_delete_non_last_item_keeps_order(
    async_client, seeded_multi_sku_order, auth_headers,
):
    """删非末项：订单保留，数量重算为剩余明细之和。"""
    order_id, item_ids = seeded_multi_sku_order
    r = await async_client.delete(f"/api/v1/orders/items/{item_ids[0]}", headers=auth_headers)
    assert r.status_code == 200, r.text
    detail = await async_client.get(f"/api/v1/orders/{order_id}", headers=auth_headers)
    assert detail.status_code == 200
    assert detail.json()["quantity"] == 200      # 只剩另一 item（手算字面量）


@pytest.mark.asyncio
async def test_delete_last_item_removes_order(
    async_client, seeded_single_item_order, auth_headers,
):
    """删末项 = 删整单：超管直删，订单消失。"""
    order_id, item_id = seeded_single_item_order
    r = await async_client.delete(f"/api/v1/orders/items/{item_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    detail = await async_client.get(f"/api/v1/orders/{order_id}", headers=auth_headers)
    assert detail.status_code == 404


@pytest.mark.asyncio
async def test_delete_first_item_moves_order_product_id(
    async_client, async_db_session, seeded_multi_sku_order, auth_headers,
):
    """删掉首个 SKU 后，order.product_id（兼容值）指向剩余明细，不留悬空（评审 I-2）。"""
    from sqlalchemy import select

    order_id, item_ids = seeded_multi_sku_order
    before = (await async_db_session.execute(
        select(Order.product_id).where(Order.id == order_id))).scalar_one()

    r = await async_client.delete(f"/api/v1/orders/items/{item_ids[0]}", headers=auth_headers)
    assert r.status_code == 200, r.text

    after = (await async_db_session.execute(
        select(Order.product_id).where(Order.id == order_id))).scalar_one()
    remaining_pid = (await async_db_session.execute(
        select(OrderItem.product_id).where(OrderItem.id == item_ids[1]))).scalar_one()
    assert after == remaining_pid, '删首项后 order.product_id 应指向剩余明细'
    assert after != before


@pytest.mark.asyncio
async def test_delete_item_with_deduction_is_rejected(
    async_client, seeded_deducted_item, auth_headers,
):
    """已被备货抵扣的 SKU 拒删（否则库存对不上）。"""
    r = await async_client.delete(
        f"/api/v1/orders/items/{seeded_deducted_item}", headers=auth_headers,
    )
    assert r.status_code == 400, r.text
    assert "抵扣" in r.json()["detail"]
