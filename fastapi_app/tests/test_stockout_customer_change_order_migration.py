"""P1-5：独立出货改客户必须迁移 order_id，否则新客户可超订单总量出货。"""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from fastapi_app.services import stock_out_service


def _stockout(**kw):
    base = {
        'id': 1, 'stockout_no': 'SO-1', 'product_id': 7, 'stockin_id': None, 'quantity': 50,
        'returned_quantity': 0, 'customer': '客户A', 'order_id': 100, 'batch_no': None,
        'stockout_date': datetime(2026, 10, 20, 2, 0, tzinfo=UTC), 'note': 'n',
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _patch_common(monkeypatch, summary: dict) -> None:
    monkeypatch.setattr(
        stock_out_service.stock_service, 'get_product_for_update',
        AsyncMock(return_value=SimpleNamespace(current_stock=1000, name='产品P')),
    )
    monkeypatch.setattr(stock_out_service, 'assert_stock_available', lambda *a, **k: None)
    monkeypatch.setattr(
        stock_out_service.stock_service, 'calculate_available_shipment_quantity',
        AsyncMock(return_value=summary),
    )


def _summary(orders: list[dict], available: int = 100) -> dict:
    return {
        'available_quantity': available,
        'order_quantity': 200,
        'shipped_quantity': 200 - available,
        'orders': orders,
    }


async def test_customer_change_migrates_order_id(monkeypatch) -> None:
    _patch_common(monkeypatch, _summary([
        {'order_id': 201, 'available': 60},
        {'order_id': 202, 'available': 40},
    ]))
    stockout = _stockout()
    db = AsyncMock()
    db.flush = AsyncMock()

    await stock_out_service.update_stockout_core(
        db, stockout, 50, '客户B', stockout.stockout_date, 'n',
    )

    assert stockout.customer == '客户B'
    assert stockout.order_id == 201


async def test_customer_change_without_single_order_capacity_is_rejected(monkeypatch) -> None:
    _patch_common(monkeypatch, _summary([
        {'order_id': 201, 'available': 30},
        {'order_id': 202, 'available': 20},
    ]))
    stockout = _stockout()
    db = AsyncMock()
    db.flush = AsyncMock()

    with pytest.raises(ValueError, match='单个订单'):
        await stock_out_service.update_stockout_core(
            db, stockout, 50, '客户B', stockout.stockout_date, 'n',
        )

    assert stockout.order_id == 100
    assert stockout.customer == '客户A'


async def test_same_customer_keeps_order_id(monkeypatch) -> None:
    _patch_common(monkeypatch, _summary([{'order_id': 100, 'available': 60}]))
    stockout = _stockout()
    db = AsyncMock()
    db.flush = AsyncMock()

    await stock_out_service.update_stockout_core(
        db, stockout, 50, '客户A', stockout.stockout_date, 'n',
    )

    assert stockout.order_id == 100


async def test_deduction_row_forces_original_customer(monkeypatch) -> None:
    _patch_common(monkeypatch, _summary([{'order_id': 201, 'available': 60}]))
    monkeypatch.setattr(
        stock_out_service, '_assert_deduction_within_stockin', AsyncMock(),
    )
    stockout = _stockout(stockin_id=5)
    db = AsyncMock()
    db.flush = AsyncMock()

    await stock_out_service.update_stockout_core(
        db, stockout, 50, '客户B', stockout.stockout_date, 'n',
    )

    assert stockout.customer == '客户A'
    assert stockout.order_id == 100


class _PidRow:
    def one_or_none(self):
        return (7,)


class _StockoutRow:
    def __init__(self, obj):
        self._obj = obj

    def scalar_one_or_none(self):
        return self._obj


async def test_update_stockout_recalcs_old_and_new_orders(monkeypatch) -> None:
    stockout = _stockout()
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[_PidRow(), _StockoutRow(stockout)])
    db.flush = AsyncMock()
    db.get = AsyncMock(return_value=SimpleNamespace(name='产品P', current_stock=950))

    monkeypatch.setattr(
        stock_out_service.stock_service, 'get_product_for_update', AsyncMock(),
    )
    monkeypatch.setattr(
        stock_out_service, '_parse_date_preserve_time',
        lambda _s: datetime(2026, 10, 20, 2, 0, tzinfo=UTC),
    )

    async def fake_core(db_, obj, *args, **kwargs):
        obj.order_id = 201  # 模拟改客户后的 order_id 迁移

    monkeypatch.setattr(stock_out_service, 'update_stockout_core', fake_core)
    recalc = AsyncMock(return_value=None)
    monkeypatch.setattr(stock_out_service, 'recalc_order_status_after_return', recalc)
    monkeypatch.setattr(stock_out_service.cache_mgr, 'invalidate_stock_and_order', AsyncMock())
    monkeypatch.setattr(stock_out_service, 'schedule_post_commit_invalidation', lambda *a, **k: None)
    monkeypatch.setattr(stock_out_service, 'safe_publish_event', AsyncMock())
    monkeypatch.setattr(stock_out_service, 'schedule_post_commit_domain_event', lambda *a, **k: None)
    monkeypatch.setattr(stock_out_service, '_publish_shipment_completed_events', AsyncMock())

    await stock_out_service.update_stockout(
        db, 1, 50, '客户B', '2026-10-20 10:00:00', 'n',
    )

    called_orders = [call.args[1] for call in recalc.await_args_list]
    assert called_orders == [100, 201]
