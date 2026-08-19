"""
Regression tests for multi-SKU BOM material generation in
generate_purchase_orders_from_customer_orders.

Verifies the fix for the bug where multi-SKU customer orders only generated
BOM materials for the primary product (Order.product_id) using the summed
quantity (Order.quantity), instead of iterating each OrderItem.

Context:
- Order.product_id = first SKU's product_id (compat field, see order_batch_create.py:134)
- Order.quantity    = sum of all OrderItem quantities (compat field, see order_batch_create.py:136)
- New code MUST iterate Order.items to compute per-SKU material quantities.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fastapi_app.services.purchase_order_generate import _iter_source_skus


def _make_order_item(
    item_id: int,
    product_id: int,
    quantity: int,
    product_name: str | None = None,
    order_type: str = 'regular',
    country: str | None = None,
    deduct_quantity: int = 0,
    note: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=item_id,
        product_id=product_id,
        product_name=product_name,
        product_barcode=None,
        quantity=quantity,
        order_type=order_type,
        country=country,
        deduct_quantity=deduct_quantity,
        note=note,
    )


def _make_order(
    order_id: int,
    order_no: str,
    customer: str,
    items: list[SimpleNamespace],
    primary_product_id: int | None = None,
    total_quantity: int | None = None,
) -> SimpleNamespace:
    """Mimics the Order model where product_id/quantity are compat fields."""
    primary_pid = primary_product_id if primary_product_id is not None else (items[0].product_id if items else 0)
    total_qty = total_quantity if total_quantity is not None else sum(it.quantity for it in items)
    return SimpleNamespace(
        id=order_id,
        order_no=order_no,
        customer=customer,
        product_id=primary_pid,
        quantity=total_qty,
        items=items,
    )


def _make_stockin(
    stockin_id: int,
    stockin_no: str,
    customer: str,
    product_id: int,
    quantity: int,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=stockin_id,
        stockin_no=stockin_no,
        customer=customer,
        product_id=product_id,
        quantity=quantity,
        # StockIn has no items attribute
    )


class TestIterSourceSkus:
    """Tests for _iter_source_skus helper that normalizes any source record
    into a list of (product_id, quantity) tuples."""

    def test_single_sku_order_returns_one_tuple(self):
        """单 SKU 订单：返回 1 个 (product_id, quantity) 元组。"""
        order = _make_order(
            order_id=1,
            order_no='DD20260720001',
            customer='客户A',
            items=[_make_order_item(10, 100, 50)],
        )

        skus = _iter_source_skus(order)

        assert skus == [(100, 50)]

    def test_multi_sku_order_returns_all_skus(self):
        """多 SKU 订单：返回所有 SKU 的 (product_id, quantity) 元组。

        Regression test for BUG: 多 SKU 订单审核后只生成主产品的 BOM 物料。
        旧实现使用 Order.product_id（仅首个 SKU）+ Order.quantity（所有 SKU 之和），
        导致 BOM 计算只覆盖主产品且数量错误。
        """
        order = _make_order(
            order_id=5,
            order_no='DD20260720005',
            customer='客户B',
            items=[
                _make_order_item(11, 101, 10),
                _make_order_item(12, 102, 20),
                _make_order_item(13, 103, 15),
            ],
            # Compat fields reflect OLD buggy state
            primary_product_id=101,
            total_quantity=45,
        )

        skus = _iter_source_skus(order)

        # Must return ALL SKUs, not just the primary
        assert skus == [(101, 10), (102, 20), (103, 15)]
        # Critical: must NOT return [(101, 45)] like the old behavior
        assert skus != [(101, 45)]

    def test_order_with_no_items_falls_back_to_compat_fields(self):
        """无 OrderItem 的旧订单：回退到 Order.product_id/quantity 兼容字段。"""
        order = SimpleNamespace(
            id=1,
            order_no='DD20260720001',
            customer='客户A',
            product_id=200,
            quantity=30,
            items=[],
        )

        skus = _iter_source_skus(order)

        assert skus == [(200, 30)]

    def test_order_with_none_items_falls_back_to_compat_fields(self):
        """items 为 None 的订单：回退到 Order.product_id/quantity 兼容字段。"""
        order = SimpleNamespace(
            id=1,
            order_no='DD20260720001',
            customer='客户A',
            product_id=200,
            quantity=30,
            items=None,
        )

        skus = _iter_source_skus(order)

        assert skus == [(200, 30)]

    def test_stockin_returns_single_sku(self):
        """StockIn 记录（单 SKU）：返回 1 个 (product_id, quantity) 元组。"""
        stockin = _make_stockin(20, 'BH20260720001', '客户C', 300, 100)

        skus = _iter_source_skus(stockin)

        assert skus == [(300, 100)]

    def test_stockin_without_items_attribute(self):
        """StockIn 没有 items 属性，不应抛异常。"""
        stockin = _make_stockin(20, 'BH20260720001', '客户C', 300, 100)

        # Verify StockIn doesn't accidentally have items
        assert not hasattr(stockin, 'items') or stockin.__dict__.get('items') is None

        skus = _iter_source_skus(stockin)

        assert skus == [(300, 100)]


class TestMultiSkuBomCalculation:
    """Integration-style tests verifying BOM material generation correctness
    for multi-SKU orders.

    These tests simulate the inner _build_items logic by using _iter_source_skus
    to verify that each SKU's BOM is consulted with its own quantity.
    """

    def test_multi_sku_bom_quantities_are_per_sku_not_total(self):
        """多 SKU 订单的物料数量应按各 SKU 数量独立计算，而非用总数。

        验证场景：
        - 订单包含 SKU A (qty=10) 和 SKU B (qty=20)
        - A 的 BOM 填充物单位用量 = 100g
        - B 的 BOM 填充物单位用量 = 50g
        - 期望：A 物料 = 100*10 = 1000g, B 物料 = 50*20 = 1000g
        - 旧 BUG：仅 A 物料 = 100*30 = 3000g（错误使用了总数）
        """
        order = _make_order(
            order_id=5,
            order_no='DD20260720005',
            customer='客户B',
            items=[
                _make_order_item(11, 101, 10),
                _make_order_item(12, 102, 20),
            ],
            primary_product_id=101,
            total_quantity=30,  # OLD buggy total
        )

        # Mock BOM data
        filling_map: dict[int, list] = {
            101: [SimpleNamespace(product_id=101, cotton_usage=100, material_code='FILL-A',
                                   specification='100g', unit='克', supplier_name='S1',
                                   supplier_id=1)],
            102: [SimpleNamespace(product_id=102, cotton_usage=50, material_code='FILL-B',
                                   specification='50g', unit='克', supplier_name='S2',
                                   supplier_id=2)],
        }

        # Simulate the FIXED _build_items behavior using _iter_source_skus
        result_items: list[dict[str, Any]] = []
        for pid, qty in _iter_source_skus(order):
            for bom in filling_map.get(pid, []):
                result_items.append({
                    'material_code': bom.material_code,
                    'quantity': float(bom.cotton_usage or 0) * qty,
                    'product_id': pid,
                })

        # Both SKUs' materials must be present
        assert len(result_items) == 2
        materials_by_code = {it['material_code']: it for it in result_items}
        assert 'FILL-A' in materials_by_code
        assert 'FILL-B' in materials_by_code

        # Per-SKU quantities (NOT total)
        assert materials_by_code['FILL-A']['quantity'] == 100 * 10  # = 1000
        assert materials_by_code['FILL-B']['quantity'] == 50 * 20   # = 1000

        # Critical: must NOT have the buggy behavior of using total qty
        assert materials_by_code['FILL-A']['quantity'] != 100 * 30  # not 3000
