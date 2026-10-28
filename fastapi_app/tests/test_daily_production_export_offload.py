"""生产报表 Excel 生成必须离开事件循环。"""
from unittest.mock import AsyncMock

import pytest

from fastapi_app.services import daily_production_service


class _EmptyResult:
    def scalars(self):
        return self

    def all(self):
        return []


@pytest.mark.asyncio
async def test_excel_render_uses_bounded_sync_executor(monkeypatch):
    db = AsyncMock()
    db.execute.return_value = _EmptyResult()
    monkeypatch.setattr(
        'fastapi_app.services.export_limits.ensure_within_export_limit',
        AsyncMock(return_value=0),
    )
    monkeypatch.setattr(
        daily_production_service,
        '_build_product_price_fallback',
        AsyncMock(return_value={}),
    )

    async def _run(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    runner = AsyncMock(side_effect=_run)
    monkeypatch.setattr(daily_production_service, 'run_sync_with_timeout', runner)

    content = await daily_production_service.export_records(
        db, start_date='2026-01-01', end_date='2026-01-31',
    )

    assert content.startswith(b'PK')
    runner.assert_awaited_once()
