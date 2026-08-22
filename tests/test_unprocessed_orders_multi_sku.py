"""
Unit tests for multi-SKU display in unprocessed orders list.

Verifies the fix for the bug where only the first SKU was shown per order
in the purchase approval page (http://192.168.0.95:3000/purchase 审核订单).
"""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi_app.services.purchase_order_query import (
    _build_unprocessed_order_record,
    _build_unprocessed_stockin_record,
)


def _make_order_item(
    item_id: int,
    product_id: int,
    product_name: str | None,
    product_barcode: str | None,
    quantity: int,
    order_type: str = 'regular',
    country: str | None = None,
    deduct_quantity: int = 0,
    note: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=item_id,
        product_id=product_id,
        product_name=product_name,
        product_barcode=product_barcode,
        quantity=quantity,
        order_type=order_type,
        country=country,
        deduct_quantity=deduct_quantity,
        note=note,
    )


_DATE_UNSET = object()


def _make_order(
    order_id: int,
    order_no: str,
    customer: str,
    items: list,
    order_date: datetime | object | None = _DATE_UNSET,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=order_id,
        order_no=order_no,
        customer=customer,
        order_date=datetime(2026, 7, 20, 10, 30, tzinfo=UTC) if order_date is _DATE_UNSET else order_date,
        items=items,
    )


class TestBuildUnprocessedOrderRecordMultiSku:
    """Tests for _build_unprocessed_order_record with multiple SKUs."""

    def test_single_sku_order_returns_one_item(self):
        """单 SKU 订单：items 数组包含 1 条记录，sku_count=1。"""
        order = _make_order(
            order_id=1,
            order_no='DD20260720001',
            customer='客户A',
            items=[_make_order_item(10, 100, '产品X', '69000001', 50)],
        )

        record = _build_unprocessed_order_record(order)

        assert record['composite_id'] == 'order:1'
        assert record['order_no'] == 'DD20260720001'
        assert record['customer'] == '客户A'
        assert record['sku_count'] == 1
        assert len(record['items']) == 1
        assert record['items'][0]['product_id'] == 100
        assert record['items'][0]['product_name'] == '产品X'
        assert record['items'][0]['product_barcode'] == '69000001'
        assert record['items'][0]['quantity'] == 50
        # Backward-compat: top-level fields reflect the first item
        assert record['product_id'] == 100
        assert record['product_name'] == '产品X'
        assert record['quantity'] == 50
        assert record['record_type'] == 'order'

    def test_multi_sku_order_returns_all_items(self):
        """多 SKU 订单：items 数组包含所有 SKU，sku_count 正确。

        Regression test for BUG: 审核订单页面一个 PO 号仅显示一个 SKU。
        """
        order = _make_order(
            order_id=5,
            order_no='DD20260720005',
            customer='客户B',
            items=[
                _make_order_item(11, 101, '产品A', '69000101', 10),
                _make_order_item(12, 102, '产品B', '69000102', 20, order_type='custom', country='美国'),
                _make_order_item(13, 103, '产品C', '69000103', 15, deduct_quantity=5, note='加急'),
            ],
        )

        record = _build_unprocessed_order_record(order)

        assert record['composite_id'] == 'order:5'
        assert record['sku_count'] == 3
        assert len(record['items']) == 3

        # Verify all SKUs are present (not just the first one)
        product_ids = [item['product_id'] for item in record['items']]
        assert product_ids == [101, 102, 103]

        # Verify each SKU's detail data
        item_by_pid = {item['product_id']: item for item in record['items']}
        assert item_by_pid[101]['product_name'] == '产品A'
        assert item_by_pid[101]['product_barcode'] == '69000101'
        assert item_by_pid[101]['quantity'] == 10
        assert item_by_pid[101]['order_type'] == 'regular'

        assert item_by_pid[102]['product_name'] == '产品B'
        assert item_by_pid[102]['order_type'] == 'custom'
        assert item_by_pid[102]['country'] == '美国'

        assert item_by_pid[103]['quantity'] == 15
        assert item_by_pid[103]['deduct_quantity'] == 5
        assert item_by_pid[103]['note'] == '加急'

        # Backward-compat: top-level still reflects the first item
        assert record['product_id'] == 101
        assert record['product_name'] == '产品A'
        assert record['quantity'] == 10

    def test_order_with_no_items_returns_empty_items_list(self):
        """无 SKU 订单：items 为空列表，sku_count=0，顶层字段为安全默认值。"""
        order = _make_order(
            order_id=9,
            order_no='DD20260720009',
            customer='客户C',
            items=[],
        )

        record = _build_unprocessed_order_record(order)

        assert record['sku_count'] == 0
        assert record['items'] == []
        assert record['product_id'] is None
        assert record['quantity'] == 0

    def test_order_date_formatting(self):
        """订单日期格式化为 YYYY-MM-DD 和 YYYY-MM-DD HH:MM。"""
        order = _make_order(
            order_id=1,
            order_no='DD20260720001',
            customer='客户A',
            items=[_make_order_item(10, 100, '产品X', '69000001', 50)],
            order_date=datetime(2026, 7, 20, 14, 30, tzinfo=UTC),
        )

        record = _build_unprocessed_order_record(order)

        assert record['order_date'] == '2026-07-20'
        assert record['create_time'] == '2026-07-20 14:30'

    def test_order_with_none_date(self):
        """订单日期为 None 时不抛异常，返回空字符串。"""
        order = _make_order(
            order_id=1,
            order_no='DD20260720001',
            customer='客户A',
            items=[_make_order_item(10, 100, '产品X', '69000001', 50)],
            order_date=None,
        )

        record = _build_unprocessed_order_record(order)

        assert record['order_date'] == ''
        assert record['create_time'] == ''


class TestBuildUnprocessedStockinRecord:
    """Tests for _build_unprocessed_stockin_record (single-SKU StockIn)."""

    def test_stockin_returns_single_item_list(self):
        """StockIn 记录封装为单元素 items 列表，前端可统一渲染。"""
        stockin = SimpleNamespace(
            id=20,
            stockin_no='BH20260720001',
            customer='客户D',
            product_id=200,
            quantity=100,
            stockin_date=datetime(2026, 7, 20, 9, 0, tzinfo=UTC),
            order_type='regular',
            country=None,
            note='备货备注',
        )

        record = _build_unprocessed_stockin_record(stockin)

        assert record['composite_id'] == 'stockin:20'
        assert record['order_no'] == 'BH20260720001'
        assert record['customer'] == '客户D'
        assert record['sku_count'] == 1
        assert len(record['items']) == 1
        assert record['items'][0]['product_id'] == 200
        assert record['items'][0]['quantity'] == 100
        assert record['items'][0]['order_type'] == 'regular'
        assert record['items'][0]['note'] == '备货备注'
        # product_name is None at build time; enriched by caller via Product query
        assert record['items'][0]['product_name'] is None
        assert record['record_type'] == 'stockin'
        assert record['order_date'] == '2026-07-20'
