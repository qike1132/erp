"""P1-22：外发订单产品筛选必须下沉到服务端（透传 beile 的 product_kw）。"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi_app.api.v1.endpoints import outsource as ep
from fastapi_app.services.outsource import _queries


async def test_service_passes_product_kw_to_beile(monkeypatch) -> None:
    from fastapi_app.services import order_crud

    beile = AsyncMock(return_value={'items': [], 'total': 0, 'page': 1, 'per_page': 10})
    monkeypatch.setattr(order_crud, 'get_beile_orders_with_stockins', beile)

    result = await _queries.list_outsource_orders(
        AsyncMock(), page=1, per_page=10, customer='客户A', product='杯',
    )

    beile.assert_awaited_once()
    assert beile.await_args.kwargs['product_kw'] == '杯'
    assert beile.await_args.kwargs['factory'] == '湖北'
    assert result['total'] == 0


async def test_process_status_branch_passes_product(monkeypatch) -> None:
    scan = AsyncMock(return_value=[])
    monkeypatch.setattr(_queries, '_scan_beile_items_with_progress', scan)
    db = AsyncMock()

    await _queries.list_outsource_orders(
        db, page=1, per_page=10, customer='客户A', product='杯', process_status='completed',
    )

    scan.assert_awaited_once_with(db, '客户A', '杯')


async def test_endpoint_forwards_product(monkeypatch) -> None:
    svc = AsyncMock(return_value={'items': [], 'total': 0, 'page': 1, 'per_page': 10})
    monkeypatch.setattr(ep.outsource_service, 'list_outsource_orders', svc)

    await ep.list_outsource_orders(
        page=1, per_page=10, customer=None, product='杯', process_status=None,
        db=AsyncMock(), _user=SimpleNamespace(),
    )

    svc.assert_awaited_once()
    assert svc.await_args.kwargs['product'] == '杯'
