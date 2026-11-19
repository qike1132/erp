import inspect
import pathlib

import pytest


def _production_py_files():
    """生产树下的 .py 文件（路径按 __file__ 解析，不依赖 cwd）。

    4.3（2026-10-17 审计 P2）：原写法 `pathlib.Path('fastapi_app')` 是**相对 cwd** 的，
    换 cwd 跑（IDE、`pytest --rootdir`、CI 子目录调用）时 rglob 扫到空集合 →
    `hits == []` 恒真，这条守卫等于不存在。并把扫描面做成自证的下限断言。
    """
    root = pathlib.Path(__file__).resolve().parents[1] / 'fastapi_app'
    files = [p for p in root.rglob('*.py') if 'tests' not in p.parts]
    # 扫描面不能为空：路径解析错 / 目录改名 / 误删时，下面的断言会「恒真」通过。
    # 本仓 fastapi_app/** 有 400+ 个 .py，100 这个阈值不可能误报。
    assert len(files) > 100, f'扫描面异常：仅 {len(files)} 个文件（root={root}）'
    return files


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
