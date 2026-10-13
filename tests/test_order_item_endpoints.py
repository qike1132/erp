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
