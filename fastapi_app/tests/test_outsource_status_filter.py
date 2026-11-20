"""外发状态筛选：必须单次 SQL 下推，不再逐页扫描（M-1 回归）。"""
import pytest

from fastapi_app.services.outsource import _queries


@pytest.mark.asyncio
async def test_process_status_uses_single_sql_query(monkeypatch):
    calls: list[dict] = []

    async def _fake_get(db, **kwargs):
        calls.append(kwargs)
        return {'items': [], 'total': 0, 'page': 1, 'per_page': 50}

    monkeypatch.setattr(
        'fastapi_app.services.order_crud.get_beile_orders_with_stockins', _fake_get,
    )

    result = await _queries.list_outsource_orders(
        object(), page=1, per_page=50, process_status='completed',
    )

    assert result['total'] == 0
    assert len(calls) == 1, '不得再逐页扫描全量列表'
    assert calls[0]['include_stockins'] is False
    assert calls[0]['cache_variant'] == 'process_status:completed'
    assert calls[0]['order_filter'] is not None
