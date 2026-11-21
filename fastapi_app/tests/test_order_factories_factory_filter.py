"""H-2（2026-11-21 全量审计）回归：厂绑定用户的 factories 字段只回本厂。

owner 裁定（2026-11-21）：items 维持全量——「任一本厂 SKU 即整单可见」是设计意图；
但 ``factories`` 字段把混厂订单的**他厂工厂名**一并带出，属于契约外泄漏。修复=
序列化/组装阶段按绑定厂过滤，未绑定用户行为不变（契约不动）。
"""
import types
from datetime import UTC, datetime

from fastapi_app.services.order.unified import _build_order_record
from fastapi_app.services.serializers.order_serializer import (
    OrderSerializer,
)


def _item(factory):
    return types.SimpleNamespace(
        id=1, order_id=10, product_id=100, product_name="P1",
        product_barcode="BC1", quantity=5, deduct_stock=True,
        deduct_quantity=2, note="",
        product=types.SimpleNamespace(
            id=100, name="P1", barcode="BC1", image="", factory=factory),
    )


def _order(item_factories):
    return types.SimpleNamespace(
        id=10, order_no="SO-1", customer="客户甲", order_date=datetime(2026, 11, 1, tzinfo=UTC),
        product=types.SimpleNamespace(id=100, name="P1", barcode="BC1", image=""),
        quantity=5, status="pending", note="", is_locked=False, locked_by=None,
        items=[_item(f) for f in item_factories],
    )


def test_serialize_filters_factories_for_factory_bound_user():
    data = OrderSerializer.serialize(
        _order(["甲厂", "乙厂"]), OrderSerializer.LIST_CONFIG, factory="甲厂")
    assert data["factories"] == ["甲厂"]


def test_serialize_factories_unchanged_without_factory_binding():
    data = OrderSerializer.serialize(_order(["甲厂", "乙厂"]), OrderSerializer.LIST_CONFIG)
    # _loaded_item_factories 按字典序输出（乙 U+4E59 < 甲 U+7532）
    assert data["factories"] == sorted(["甲厂", "乙厂"])


def test_serialize_filters_precomputed_factories_path():
    data = OrderSerializer.serialize(
        _order(["甲厂"]), OrderSerializer.LIST_CONFIG,
        factory="乙厂", item_factories=["甲厂", "乙厂"])
    assert data["factories"] == ["乙厂"]


def test_serialize_keeps_empty_factories_for_bound_user_without_match():
    data = OrderSerializer.serialize(
        _order(["甲厂"]), OrderSerializer.LIST_CONFIG, factory="乙厂")
    assert data["factories"] == []


def test_build_order_record_filters_factories_for_factory_bound_user():
    record = _build_order_record(_order(["甲厂", "乙厂"]), 0, ["甲厂", "乙厂"], factory="甲厂")
    assert record["factories"] == ["甲厂"]


def test_build_order_record_unchanged_without_factory_binding():
    record = _build_order_record(_order(["甲厂", "乙厂"]), 0, ["甲厂", "乙厂"])
    assert record["factories"] == ["甲厂", "乙厂"]
