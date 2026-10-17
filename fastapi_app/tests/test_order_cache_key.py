"""订单列表缓存键回归测试（2026-10-17 审计 AUD-05）

缺陷：get_orders 的 @cache_result key_builder 漏了 keyword，同条件不同搜索词
命中同一缓存条目，搜索结果串台最长 60s（L2 TTL）。

本测试锁定：所有参与筛选的参数都必须进入缓存键，且 keyword 不同键必须不同。
"""
from fastapi_app.services.order.queries import _orders_list_cache_key

BASE = {
    'page': 1,
    'per_page': 50,
    'customer': '',
    'product_id': None,
    'status': '',
    'start_date': '',
    'end_date': '',
    'factory': '',
}


def test_keyword_changes_cache_key():
    """AUD-05 的核心断言：不同搜索词不得共享缓存键"""
    key_a = _orders_list_cache_key(**{**BASE, 'keyword': '张三'})
    key_b = _orders_list_cache_key(**{**BASE, 'keyword': '李四'})

    assert key_a != key_b
    assert '张三' in key_a and '李四' in key_b


def test_keyword_none_equals_empty():
    """未传 keyword 与传空串应等价（避免无谓的缓存分裂）"""
    assert (
        _orders_list_cache_key(**{**BASE, 'keyword': None})
        == _orders_list_cache_key(**{**BASE, 'keyword': ''})
        == _orders_list_cache_key(**BASE)
    )


def test_all_filter_params_participate():
    """逐个参数改动都必须改变缓存键（防止再漏参）"""
    baseline = _orders_list_cache_key(**{**BASE, 'keyword': 'kw'})
    for param, value in [
        ('page', 2), ('per_page', 20), ('customer', '客户A'), ('product_id', 7),
        ('status', '已出货'), ('start_date', '2026-01-01'),
        ('end_date', '2026-01-31'), ('factory', '一厂'),
    ]:
        assert _orders_list_cache_key(**{**BASE, 'keyword': 'kw', param: value}) != baseline, (
            f'{param} 未进入缓存键，仍可能串台'
        )
