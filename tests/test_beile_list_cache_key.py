"""湖北列表缓存键必须区分完整/轻量查询（H-1 回归）。

根因：`get_beile_orders_with_stockins(skip_po_maps=True)`（外发列表）与
False（湖北订单页）共用同一 Redis 键，轻量响应会把 is_ordered /
purchase_order_qty 清空后污染湖北订单页最长 60s。
"""
import pytest

from fastapi_app.services.order import beile
from fastapi_app.services.order.beile import _beile_list_cache_key

_BASE = {
    'page': 1, 'per_page': 50, 'customer': '客户A', 'factory': '湖北',
    'confirm_status': '', 'product_kw': '',
}


def test_skip_flag_changes_cache_key():
    full = _beile_list_cache_key(**_BASE, skip_po_maps=False)
    light = _beile_list_cache_key(**_BASE, skip_po_maps=True)

    assert full != light, '完整查询与轻量查询不得共用缓存键'
    assert ':sp0:' in full
    assert ':sp1:' in light


def test_include_stockins_and_variant_change_cache_key():
    base = _beile_list_cache_key(**_BASE)
    no_stockins = _beile_list_cache_key(**_BASE, include_stockins=False)
    variant = _beile_list_cache_key(
        **_BASE, include_stockins=False, cache_variant='process_status:pending',
    )

    assert len({base, no_stockins, variant}) == 3
    assert ':vprocess_status:pending' in variant


def test_default_is_full_form():
    assert _beile_list_cache_key(**_BASE) == _beile_list_cache_key(
        **_BASE, skip_po_maps=False,
    )


async def test_order_filter_requires_cache_variant():
    with pytest.raises(ValueError, match='cache_variant'):
        await beile.get_beile_orders_with_stockins.__wrapped__(
            None, order_filter=object(),
        )
