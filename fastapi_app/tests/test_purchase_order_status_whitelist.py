"""P1-16：采购订单状态白名单（DTO + 服务层）。"""
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from fastapi_app.api.v1.endpoints.purchase_center.schemas import PurchaseOrderUpdateRequest
from fastapi_app.services.purchase_order_crud import _apply_order_field_updates
from fastapi_app.shared_models.purchase_order import PurchaseOrderStatus


def test_update_dto_rejects_unknown_status() -> None:
    with pytest.raises(ValidationError):
        PurchaseOrderUpdateRequest(status='bogus')

    for value in PurchaseOrderStatus.ALL:
        assert PurchaseOrderUpdateRequest(status=value).status == value
    assert PurchaseOrderUpdateRequest(status=None).status is None


def test_service_rejects_unknown_status() -> None:
    order = SimpleNamespace(status=PurchaseOrderStatus.PENDING)

    with pytest.raises(ValueError, match='非法采购订单状态'):
        _apply_order_field_updates(order, {'status': 'bogus'})
    assert order.status == PurchaseOrderStatus.PENDING

    _apply_order_field_updates(order, {'status': PurchaseOrderStatus.COMPLETED})
    assert order.status == PurchaseOrderStatus.COMPLETED

    # 显式 None 视为不修改（DTO 的 exclude_unset 语义）
    _apply_order_field_updates(order, {'status': None})
    assert order.status == PurchaseOrderStatus.COMPLETED
