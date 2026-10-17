"""ARQ 批量导入「数量必须为正整数」守卫（2026-10-17 审计 F-BE-CORE-01）。

原实现 `_resolve_row_product` 用 `all([..., quantity])` 判必填，负数是 truthy
顺利通过，`-50` 会落成 StockIn(-50) + apply_stock_delta_locked(-50)（库存被扣）
+ InventoryLog(change_type='备货入库', change_quantity=-50)（流水方向与类型矛盾）。

守卫口径与 batch_import_core._parse_positive_quantity（qty>0 else None）、
plan_tasks（quantity<=0 拒行）一致：负数/零/小数/非数值一律拒行。
"""
import pytest

import fastapi_app.tasks.batch_tasks as bt


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'bad_quantity',
    [-50, 0, -0.5, 1.9, 'abc', None, True],
    ids=['negative', 'zero', 'negative-float', 'float', 'str', 'none', 'bool'],
)
async def test_rejects_non_positive_quantity(bad_quantity):
    row = {'产品名称': 'P', '客户名称': 'c', '数量': bad_quantity}
    product, error = await bt._resolve_row_product(object(), row)
    assert product is None
    assert error is not None
    # 0/None 在必填分支即被拒（falsy），负数/小数/非数值落到数量守卫
    if bad_quantity not in (0, None):
        assert '数量无效' in error


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'ok_quantity',
    [1, 50, 1000, 50.0],
    ids=['int', 'int-large', 'int-1000', 'float-integral'],
)
async def test_accepts_positive_integer_quantity(ok_quantity, monkeypatch):
    # 数量守卫通过后才走产品解析；把 _resolve_product_locked 桩掉隔离 DB。
    sent_product = object()
    monkeypatch.setattr(bt, '_resolve_product_locked',
                        __import__('unittest').mock.AsyncMock(return_value=sent_product))
    row = {'产品名称': 'P', '客户名称': 'c', '数量': ok_quantity}
    product, error = await bt._resolve_row_product(object(), row)
    assert error is None
    assert product is sent_product
