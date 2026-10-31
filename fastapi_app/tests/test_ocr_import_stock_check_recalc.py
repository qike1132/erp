"""OCR/图片出货单导入的结余预检回归（2026-10-30 审计 A-M12）。

`_build_staging_row` 只用 `product.current_stock` 判库存，而确认环节的闸门
（`_confirm_one_staging_stockout`）用的是「结余 = 包装部入库 − 已出货」。
两者口径不一致时，OCR 导入的行会带着 `stock_check_passed=True` 进弹窗，
用户点确认却被逐行拒绝并批删——数据静默丢失。

修复：写入暂存区 flush 后，按结余口径重算本 session 的 stock_check。
本文件锁定「必须调用重算」这一接线，避免以后被重构掉。
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.services.ocr import _import as ocr_import


def _db(products):
    db = MagicMock()
    nested = MagicMock()
    nested.__aenter__ = AsyncMock(return_value=None)
    nested.__aexit__ = AsyncMock(return_value=False)
    db.begin_nested = MagicMock(return_value=nested)

    product_result = MagicMock()
    product_result.scalars.return_value.all.return_value = products
    customer_result = MagicMock()
    customer_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(side_effect=[product_result, customer_result])
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_recalcs_stock_check_by_balance_after_flush():
    product = MagicMock()
    product.name = '测试产品'
    product.barcode = ''
    product.current_stock = 1000

    db = _db([product])
    with patch.object(
        ocr_import, '_recognize_items',
        new=AsyncMock(return_value=([{'product_name': '测试产品', 'customer': '客户A', 'quantity': 10}], [], [])),
    ), patch(
        'fastapi_app.services.staging.stockout._recalc_stock_check_by_balance',
        new=AsyncMock(),
    ) as m_recalc:
        imported, _msg, errors = await ocr_import.import_staging_stockouts_from_file(
            db, b'fake', 'sess-1', filename='a.pdf',
        )

    assert imported == 1
    assert errors == []
    # 关键断言：必须按结余口径重算，且作用于本 session
    assert m_recalc.await_count == 1
    assert m_recalc.await_args.args[0] is db
    assert m_recalc.await_args.args[1] == 'sess-1'
    # 顺序：先 flush 再重算（重算要能读到刚写入的行）
    assert db.flush.await_count == 1
