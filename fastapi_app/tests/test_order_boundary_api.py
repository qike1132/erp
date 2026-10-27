"""订单核心链路的数量边界与 API 契约回归测试。"""
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from fastapi_app.schemas.order import OrderCreate, OrderUpdate


@pytest.mark.unit
@pytest.mark.parametrize("quantity", [1, 9_999_999])
def test_order_create_accepts_quantity_boundaries(quantity: int) -> None:
    """最小值和最大值均应通过真实 Schema 校验。"""
    order = OrderCreate(product_id=1, quantity=quantity, customer="边界客户")
    assert order.quantity == quantity


@pytest.mark.unit
@pytest.mark.parametrize("quantity", [0, -1, 10_000_000])
def test_order_create_rejects_quantity_outside_boundaries(quantity: int) -> None:
    """零、负数和超过上限的数量不得进入业务层。"""
    with pytest.raises(ValidationError):
        OrderCreate(product_id=1, quantity=quantity, customer="边界客户")


@pytest.mark.unit
def test_order_update_rejects_over_limit_quantity() -> None:
    """部分更新与创建必须共用相同的数量上限。"""
    with pytest.raises(ValidationError):
        OrderUpdate(quantity=10_000_000)


@pytest.mark.api
class TestOrderCreateBoundaryApi:
    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("product_id", 0),
            ("quantity", 0),
            ("quantity", -1),
            ("quantity", 10_000_000),
            ("customer", ""),
            ("customer", "客" * 101),
        ],
    )
    async def test_invalid_payload_is_422_before_business_side_effects(
        self, client, field: str, value
    ) -> None:
        """非法请求统一返回 422，且不触达工厂检查或订单创建服务。"""
        payload = {"product_id": 1, "quantity": 1, "customer": "边界客户"}
        payload[field] = value
        with (
            patch(
                "fastapi_app.api.v1.endpoints.order.assert_product_factory_scoped",
                new_callable=AsyncMock,
            ) as factory_check,
            patch(
                "fastapi_app.api.v1.endpoints.order.order_service.create_order",
                new_callable=AsyncMock,
            ) as create,
        ):
            response = await client.post("/api/v1/orders/create", json=payload)

        assert response.status_code == 422, response.text
        body = response.json()
        assert body["success"] is False
        assert body["status_code"] == 422
        factory_check.assert_not_awaited()
        create.assert_not_awaited()

    async def test_upper_boundary_reaches_service_without_contract_changes(self, client) -> None:
        """最大合法数量应沿真实 API 边界原样传递给订单服务。"""
        with (
            patch(
                "fastapi_app.api.v1.endpoints.order.assert_product_factory_scoped",
                new_callable=AsyncMock,
            ),
            patch(
                "fastapi_app.api.v1.endpoints.order.order_service.create_order",
                new_callable=AsyncMock,
            ) as create,
            patch(
                "fastapi_app.api.v1.endpoints.order.cache_mgr.invalidate_dashboard",
                new_callable=AsyncMock,
            ),
        ):
            response = await client.post(
                "/api/v1/orders/create",
                json={"product_id": 7, "quantity": 9_999_999, "customer": "边界客户"},
            )

        assert response.status_code == 200, response.text
        assert response.json() == {"success": True, "message": "订单添加成功！"}
        assert create.await_args.kwargs["product_id"] == 7
        assert create.await_args.kwargs["quantity"] == 9_999_999
        assert create.await_args.kwargs["customer"] == "边界客户"
