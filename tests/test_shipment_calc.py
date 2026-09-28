from types import SimpleNamespace

from fastapi_app.shared.shipment_calc import build_shipment_summary


def _order(oid, qty):
    return SimpleNamespace(id=oid, order_no=f'NO{oid}', quantity=qty)


def test_summary_has_no_regular_custom_split():
    result = build_shipment_summary([_order(1, 10)], {1: 3})
    assert result['order_quantity'] == 10
    assert result['available_quantity'] == 7
    assert 'regular_available' not in result
    assert 'custom_available' not in result


def test_order_detail_has_no_type_or_country():
    result = build_shipment_summary([_order(1, 10)], {})
    assert result['orders'][0] == {
        'order_id': 1, 'order_no': 'NO1', 'quantity': 10,
        'shipped': 0, 'available': 10,
    }


def test_empty_orders_shape():
    assert build_shipment_summary([], {}) == {
        'order_quantity': 0, 'shipped_quantity': 0,
        'available_quantity': 0, 'orders': [],
    }
