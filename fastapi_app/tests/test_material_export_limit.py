"""来料登记导出上限的显式拒绝回归（2026-10-30 审计 A-M24）。

原实现在命中 `limit(5000)` 时只打一条 WARNING 就照常导出——用户拿到的是一份
**缺行**的 Excel，界面上没有任何提示，对账时才发现少数据（静默丢数据）。

修复：超过上限直接拒绝（ValueError → 端点映射 400），让用户缩小筛选范围重试。
本文件锁定「拒绝」而不是「截断」，并锁定 400 的状态码映射。
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.services.material_registration import _export as export_mod


def _db(count):
    result = MagicMock()
    result.scalar.return_value = count
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    return db


@pytest.mark.asyncio
async def test_rejects_when_row_count_exceeds_limit():
    db = _db(5001)

    with pytest.raises(ValueError) as ei:
        await export_mod.export_registrations(db)

    msg = str(ei.value)
    assert '5000' in msg
    assert '5001' in msg
    # 拒绝发生在主查询之前：不应再取数据行
    assert db.execute.await_count == 1


@pytest.mark.asyncio
async def test_allows_at_limit():
    """恰好 5000 条仍可导出（上限含等于）。"""
    db = _db(5000)
    # 主查询返回空行，函数会正常生成 xlsx
    main_result = MagicMock()
    main_result.scalars.return_value.unique.return_value.all.return_value = []
    db.execute = AsyncMock(side_effect=[_db(5000).execute.return_value, main_result])

    buffer = await export_mod.export_registrations(db)
    assert buffer.getvalue()[:2] == b'PK'  # xlsx(zip) 魔数


@pytest.mark.asyncio
async def test_endpoint_maps_value_error_to_400(client):
    """端点必须把「超上限」映射成 400 而不是 500。"""
    with patch(
        'fastapi_app.services.material_registration_service.export_registrations',
        new=AsyncMock(side_effect=ValueError('符合条件的数据共 6000 条，超过单次导出上限 5000 条')),
    ):
        resp = await client.post('/api/v1/material-registrations/export', json={})

    assert resp.status_code == 400
    assert '5000' in resp.json()['detail']
