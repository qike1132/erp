"""外发列表必须走轻量 beile 查询：跳过 PO/逐 SKU 注入（审计 M-05）。"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi_app.services import order_crud
from fastapi_app.services.order import beile
from fastapi_app.services.outsource import _queries


def _patch_light_beile(monkeypatch, calls):
    async def fake(db, **kwargs):
        calls.append(kwargs)
        return {'items': [], 'total': 0, 'page': 1, 'per_page': 50}

    async def fake_attach(db, items):
        return None

    monkeypatch.setattr(order_crud, 'get_beile_orders_with_stockins', fake)
    monkeypatch.setattr(_queries, '_attach_progress_to_orders', fake_attach)




async def test_list_without_status_uses_light_beile_query(monkeypatch):
    calls: list[dict] = []
    _patch_light_beile(monkeypatch, calls)

    await _queries.list_outsource_orders(None, page=1, per_page=50)

    assert calls, '应调用 beile 查询'
    assert calls[0].get('skip_po_maps') is True


async def test_skip_po_maps_avoids_po_and_sku_queries(monkeypatch):
    """行为断言：轻量路径不得调用 completed PO / 逐 SKU 映射。"""
    forbidden = AsyncMock(side_effect=AssertionError('轻量路径不得注入 PO 映射'))
    monkeypatch.setattr(beile, 'get_beile_unconfirmed_count', AsyncMock(return_value=0))
    monkeypatch.setattr(beile, '_fetch_completed_po_maps', forbidden)
    monkeypatch.setattr(beile, '_fetch_po_sku_maps', forbidden)

    db = AsyncMock()
    db.execute = AsyncMock(return_value=SimpleNamespace(all=lambda: []))

    result = await beile.get_beile_orders_with_stockins.__wrapped__(
        db, skip_po_maps=True,
    )

    assert result['items'] == []
    forbidden.assert_not_awaited()


async def test_full_query_still_fetches_po_maps(monkeypatch):
    monkeypatch.setattr(beile, 'get_beile_unconfirmed_count', AsyncMock(return_value=0))
    po_maps = AsyncMock(return_value=({}, {}, {}))
    sku_maps = AsyncMock(return_value=({}, {}))
    monkeypatch.setattr(beile, '_fetch_completed_po_maps', po_maps)
    monkeypatch.setattr(beile, '_fetch_po_sku_maps', sku_maps)

    db = AsyncMock()
    db.execute = AsyncMock(return_value=SimpleNamespace(all=lambda: []))

    await beile.get_beile_orders_with_stockins.__wrapped__(db, skip_po_maps=False)

    po_maps.assert_awaited_once()
    sku_maps.assert_awaited_once()
