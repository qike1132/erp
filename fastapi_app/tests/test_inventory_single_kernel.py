"""Z03-R1：兼容入口 get_inventory 必须委托分页版，不得再有第二套聚合实现。"""
import inspect

import pytest

from fastapi_app.services import stock_inventory_service as svc


@pytest.mark.asyncio
async def test_get_inventory_delegates_to_paginated(monkeypatch):
    captured = {}

    async def fake_paginated(db, **kwargs):
        captured.update(kwargs)
        return {
            'inventory_data': [{'customer': 'C', 'product_name': 'P'}],
            'total_order_qty': 1,
            'total_stockin_qty': 2,
            'total_stock': 3,
        }

    monkeypatch.setattr(svc, 'get_inventory_paginated', fake_paginated)

    result = await inspect.unwrap(svc.get_inventory)(
        object(), search_customer='C', search_product='P',
    )

    assert captured == {'search_customer': 'C', 'search_product': 'P', 'page': 1, 'per_page': 100_000}
    assert result == {
        'inventory_data': [{'customer': 'C', 'product_name': 'P'}],
        'total_order_qty': 1,
        'total_stockin_qty': 2,
        'total_stock': 3,
    }


def test_old_fetch_inventory_removed():
    """旧的三表 Python 合并实现必须已删除（防止被重新引入）。"""
    assert not hasattr(svc, '_fetch_inventory')
    assert not hasattr(svc, '_merge_inventory_rows')
