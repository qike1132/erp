"""M5：订单创建必须接入工厂隔离闸门。"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_single_create_calls_factory_gate(monkeypatch):
    from fastapi_app.api.v1.endpoints import order as ep

    called = []

    async def _gate(db, pid, user, *, what):
        called.append((pid, what))

    class _CM:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(ep, "assert_product_factory_scoped", _gate, raising=False)
    monkeypatch.setattr(ep, "db_transaction", lambda db: _CM())
    monkeypatch.setattr(ep.order_service, "create_order", AsyncMock(return_value={}))
    monkeypatch.setattr(ep.cache_mgr, "invalidate_dashboard", AsyncMock())

    data = SimpleNamespace(product_id=42, quantity=1, customer="C", note="")
    await ep.create_order(
        data=data,
        db=AsyncMock(),
        user=SimpleNamespace(factory="东莞", is_super=False, username="u"),
    )

    assert called == [(42, "产品")]


@pytest.mark.asyncio
async def test_batch_create_calls_factory_gate(monkeypatch):
    import fastapi_app.services.auxiliary_service as svc
    from fastapi_app.api.v1.endpoints import auxiliary as ep

    called = []

    async def _gate(db, pid, user, *, what):
        called.append(pid)

    monkeypatch.setattr(ep, "assert_product_factory_scoped", _gate)
    monkeypatch.setattr(svc, "orchestrate_batch_orders", AsyncMock(return_value={}))

    item1 = SimpleNamespace(product_id=1, model_dump=lambda: {})
    item2 = SimpleNamespace(product_id=2, model_dump=lambda: {})
    data = SimpleNamespace(orders=[item1, item2])

    await ep.batch_submit_orders(
        data=data,
        user=SimpleNamespace(factory="东莞", is_super=False, username="u"),
        db=AsyncMock(),
    )

    assert called == [1, 2]
