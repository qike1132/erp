"""锁序回归：凡同时锁 Product 与 StockIn 的路径必须一律 **Product → StockIn**。

背景（2026-10-02 第二轮审计）：`order/deduction`、`order_batch_create` 是
Product→StockIn，而 `stock_in_service.update_stockin/delete_stockin` 曾是
**StockIn→Product** —— 两条路径命中同一产品/同一条备货时互相等锁，PostgreSQL 检出
后回滚其一（表现为 500/409，**无数据损坏**）。

本测试用**源码顺序**钉住规范锁序，防回归。改这两处前请先读 `stock_in_service`
里的锁序说明（先无锁读 product_id，再按序加锁）。
"""
import importlib
import inspect

import pytest

# (模块, 函数名) —— 同时持有 Product 与 StockIn 两把锁的路径
CASES = [
    ('fastapi_app.services.stock_in_service', 'update_stockin'),
    ('fastapi_app.services.stock_in_service', 'delete_stockin'),
    ('fastapi_app.services.order.deduction', '_increase_deduction'),
]


@pytest.mark.parametrize('mod, name', CASES, ids=[f'{m.rsplit(".", 1)[-1]}.{n}' for m, n in CASES])
def test_product_lock_precedes_stockin_lock(mod: str, name: str) -> None:
    src = inspect.getsource(getattr(importlib.import_module(mod), name))
    i_product = src.find('get_product_for_update')
    i_stockin = src.find('with_for_update')
    assert i_product != -1, f'{mod}.{name} 应通过 get_product_for_update 锁 Product'
    assert i_stockin != -1, f'{mod}.{name} 应通过 with_for_update 锁 StockIn'
    assert i_product < i_stockin, (
        f'{mod}.{name} 的锁序反了：StockIn 出现在 Product 之前。'
        '须统一为 Product → StockIn，否则与 order 侧互等锁会死锁（500/409）。'
    )
