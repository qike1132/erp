from fastapi_app.schemas.order import OrderCreate


def test_order_create_has_no_order_type_field():
    assert 'order_type' not in OrderCreate.model_fields


def test_order_create_has_no_country_field():
    assert 'country' not in OrderCreate.model_fields


def test_order_create_ignores_legacy_custom_payload():
    # 旧客户端仍可能传这两个字段：Pydantic 默认忽略未知字段，不应报错
    payload = {'product_id': 1, 'customer': '客户A', 'quantity': 5,
               'order_type': 'custom', 'country': '日本'}
    obj = OrderCreate(**payload)
    assert obj.quantity == 5
