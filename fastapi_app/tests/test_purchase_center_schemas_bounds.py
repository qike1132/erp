"""AUD-05 / B3-06（2026-10-24 审计）回归锁：采购中心请求 schema 的数值与列表界。

FactorySummaryEditItem.quantity 原先无界：负数可落库并参与金额重算为负
（服务层 Decimal(str(new_quantity)) 直写、DB 无 CHECK），NaN/Inf 在 flush 期
才炸 NumericValueOutOfRange → 500。兄弟字段 PurchaseOrderMaterialItem.quantity
早已示范「入口拦成 422」的修法，此处对齐同口径，并给漏界的请求列表补 max_length。
"""
import math

import pytest
from pydantic import ValidationError

from fastapi_app.api.v1.endpoints.purchase_center.schemas import (
    FactorySummaryEditItem,
    FactorySummarySaveRequest,
    PurchaseOrderCreateRequest,
    SupplierExportQuantityItem,
)


def test_edit_item_quantity_rejects_negative():
    with pytest.raises(ValidationError):
        FactorySummaryEditItem(item_ids=[1], quantity=-100)


def test_edit_item_quantity_rejects_nan_and_inf():
    with pytest.raises(ValidationError):
        FactorySummaryEditItem(item_ids=[1], quantity=math.nan)
    with pytest.raises(ValidationError):
        FactorySummaryEditItem(item_ids=[1], quantity=math.inf)


def test_edit_item_quantity_accepts_legal_values():
    item = FactorySummaryEditItem(item_ids=[1], quantity=0)
    assert item.quantity == 0
    item = FactorySummaryEditItem(item_ids=[1], quantity=9999999999.99)
    assert item.quantity == 9999999999.99
    # None = 不改数量（既有语义），必须保持可用
    assert FactorySummaryEditItem(item_ids=[1]).quantity is None


def test_edit_item_rejects_oversized_item_ids():
    with pytest.raises(ValidationError):
        FactorySummaryEditItem(item_ids=list(range(501)))


def test_save_request_lists_bounded():
    edits = [FactorySummaryEditItem(item_ids=[i]) for i in range(501)]
    with pytest.raises(ValidationError):
        FactorySummarySaveRequest(edits=edits)
    with pytest.raises(ValidationError):
        FactorySummarySaveRequest(order_ids=list(range(501)))


def test_supplier_export_quantity_rejects_negative():
    with pytest.raises(ValidationError):
        SupplierExportQuantityItem(
            supplier_name='供应商', material_name='物料', quantity=-1)


def _order_payload(materials):
    return {
        'materials': materials,
        'customer_name': '客户A',
    }


def test_purchase_create_materials_bounded():
    row = {
        'material_name': '布', 'unit_price': 1.0, 'quantity': 1.0,
    }
    with pytest.raises(ValidationError):
        PurchaseOrderCreateRequest(**_order_payload([row] * 501))
