import importlib

import pytest


@pytest.mark.parametrize('module,cls', [
    ('fastapi_app.shared_models.order', 'Order'),
    ('fastapi_app.shared_models.order_item', 'OrderItem'),
    ('fastapi_app.shared_models.stock_in', 'StockIn'),
    ('fastapi_app.shared_models.staging_order', 'StagingOrder'),
    ('fastapi_app.shared_models.staging_stock_out', 'StagingStockOut'),
])
def test_model_has_no_custom_fields(module, cls):
    model = getattr(importlib.import_module(module), cls)
    cols = set(model.__table__.columns.keys())
    assert 'order_type' not in cols, f'{cls} 仍有 order_type 列'
    assert 'country' not in cols, f'{cls} 仍有 country 列'


def test_country_model_removed():
    with pytest.raises(ImportError):
        importlib.import_module('fastapi_app.shared_models.country')
