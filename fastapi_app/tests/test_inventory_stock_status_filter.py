"""库存状态筛选回归（2026-10-17 审计 AUD-22）

移动端「零库存/在库」此前在截断后的首页数据上本地过滤，跨页结果失真。
现下推服务端：stock_status=zero|active 进入 CTE 过滤并参与缓存键。
"""
from fastapi_app.services.stock_inventory_service import (
    _build_inventory_cte_sql,
    _build_inventory_filter_params,
)


def test_stock_status_is_bound_and_filters_in_sql():
    params, clauses, _ = _build_inventory_filter_params('', '', None, 'zero')

    assert params['stock_status'] == 'zero'
    sql = str(_build_inventory_cte_sql(clauses))
    assert ":stock_status <> 'zero'" in sql
    assert ":stock_status <> 'active'" in sql


def test_empty_stock_status_keeps_all_rows():
    params, clauses, _ = _build_inventory_filter_params('', '', None, '')

    assert params['stock_status'] == ''
    sql = str(_build_inventory_cte_sql(clauses))
    # 空串时两个条件恒真，不改变原结果集
    assert ":stock_status <> 'zero'" in sql
