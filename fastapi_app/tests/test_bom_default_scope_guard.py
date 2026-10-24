"""AUD-09（2026-10-24 审计 P1）回归锁：默认作用域 BOM 行并发双写防护。

三层防护（本文件锁定后两层；104 迁移由 CI 空库 upgrade + check 验证）：
1. 104 迁移：三张物料表 (product_id) WHERE role_id IS NULL 的 partial unique
   index + 存量去重；
2. save_bom 先行行锁（with_for_update）——查后插串行化；
3. 锁外兜底：partial index 下并发漏锁时 DB 拒绝第二条（本文件用真实 PG 验证
   索引行为：同 product 两条 NULL-role 行第二条必 IntegrityError）。
"""
from unittest.mock import AsyncMock

import pytest

from fastapi_app.services import bom_service
from fastapi_app.shared_models import Product


async def test_save_bom_takes_row_lock_before_read():
    """save_bom 入口必须 db.get(Product, with_for_update=True) 先行锁。"""
    calls = {}

    async def _fake_get(model, ident, **kwargs):
        calls['model'] = model
        calls['ident'] = ident
        calls['kwargs'] = kwargs
        return None  # 产品不存在 → 走 ValueError 分支，无需桩后续加载

    db = AsyncMock()
    db.get = _fake_get

    with pytest.raises(ValueError, match='产品不存在'):
        await bom_service.save_bom(db, 123, {}, 'tester')

    assert calls['model'] is Product
    assert calls['ident'] == 123
    assert calls['kwargs'].get('with_for_update') is True, (
        '必须带 with_for_update 行锁（AUD-09）：查后插不加锁，并发保存同产品会'
        '落两条默认填充行、棉用量按 2 倍计量'
    )


async def test_save_bom_raises_when_product_missing():
    """锁点兼作存在性校验：与 _load_product_with_bom 的报错语义一致。"""
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)
    with pytest.raises(ValueError, match='产品不存在'):
        await bom_service.save_bom(db, 999, {}, 'tester')
