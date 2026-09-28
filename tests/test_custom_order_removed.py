import inspect
import pathlib

import pytest


def _production_py_files():
    root = pathlib.Path('fastapi_app')
    for path in root.rglob('*.py'):
        if 'tests' in path.parts:
            continue
        yield path


def test_no_production_code_raises_custom_country_error():
    """生产代码中不应再出现定制订单国家校验文案。"""
    hits = [
        str(p) for p in _production_py_files()
        if '定制订单必须填写国家名称' in p.read_text(encoding='utf-8')
    ]
    assert hits == [], f'仍存在定制订单校验: {hits}'


def test_order_list_endpoint_has_no_order_type_param():
    from fastapi_app.api.v1.endpoints import order as order_ep

    params = set(inspect.signature(order_ep.list_orders).parameters)
    assert 'order_type' not in params
    assert 'country' not in params


@pytest.mark.parametrize('fn', ['list_stockins', 'list_stockouts', 'create_stockout'])
def test_stock_endpoint_has_no_order_type_param(fn):
    from fastapi_app.api.v1.endpoints import stock as stock_ep

    params = set(inspect.signature(getattr(stock_ep, fn)).parameters)
    assert 'order_type' not in params
    assert 'country' not in params


def test_stock_inventory_endpoint_has_no_country_param():
    from fastapi_app.api.v1.endpoints import stock as stock_ep

    assert 'country' not in set(inspect.signature(stock_ep.inventory).parameters)


def test_stock_stats_model_has_no_custom_fields():
    from fastapi_app.api.v1.endpoints import stock as stock_ep

    fields = set(stock_ep.StockStatsData.model_fields)
    assert 'order_custom_quantity' not in fields
    assert 'order_regular_quantity' not in fields
