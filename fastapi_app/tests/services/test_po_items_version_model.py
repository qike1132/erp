"""PurchaseOrder.items_version 模型契约。

items_version 是采购明细版本号：BOM 实时同步与用户编辑都会递增该值，
供保存接口做 409 并发保护（详见设计文档 2026-11-11-bom-live-sync）。
"""
from fastapi_app.shared_models import PurchaseOrder


def test_items_version_defaults_to_zero():
    order = PurchaseOrder(order_no='PO-T-1', product_quantity=100)
    assert order.items_version == 0


def test_items_version_is_int_column():
    col = PurchaseOrder.__table__.c.items_version
    assert col.nullable is False
    assert col.default.arg == 0
