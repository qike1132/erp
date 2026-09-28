from fastapi_app.services import stock_inventory_service as svc


def _empty_clauses() -> dict:
    return {
        'si_pid': '', 'si_cust': '', 'so_pid': '', 'so_cust': '',
        'oi_or_o_pid': '', 'o_cust': '', 'o_not_deleted': '',
        'prod_pid': '', 'pso_pid': '', 'sub_pid': '',
    }


def test_no_country_helpers_remain():
    assert not hasattr(svc, '_parse_country_data')
    assert not hasattr(svc, '_get_all_countries')
    assert not hasattr(svc, '_build_country_data_dict')


def test_inventory_paginated_has_no_country_param():
    import inspect

    params = set(inspect.signature(svc.get_inventory_paginated).parameters)
    assert 'country' not in params


def test_stockins_stockouts_have_no_order_type_param():
    import inspect

    for fn in (svc.get_stockins, svc.get_stockouts):
        assert 'order_type' not in set(inspect.signature(fn).parameters), fn.__name__


def test_cte_has_no_custom_or_country_sql():
    sql = str(svc._build_inventory_cte_sql(_empty_clauses()))
    # 注意：不能用裸 'custom' 断言——'customer' 包含该子串
    assert "'custom'" not in sql
    assert 'custom_order_qty' not in sql
    assert 'custom_stockout_qty' not in sql
    assert 'country_agg' not in sql
    assert 'country_data' not in sql


def test_cte_total_order_is_order_plus_stockin():
    """总订单 = 订单余量 + 备货量（不再含定制余量）。"""
    sql = str(svc._build_inventory_cte_sql(_empty_clauses()))
    assert 'SUM(f.remaining) OVER() AS sum_order' in sql
    assert 'SUM(f.stockin_qty) OVER() AS sum_stockin' in sql
    assert 'remaining_cus' not in sql


def test_overview_stats_has_no_custom_split():
    import inspect

    src = inspect.getsource(svc.get_stock_overview_stats)
    assert 'order_custom_quantity' not in src
    assert 'order_regular_quantity' not in src
