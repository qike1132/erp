"""BOM 保存/复制端点必须清空采购中心选品缓存（审计 M-06/M-5 回归）。"""
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from fastapi_app.api.v1.endpoints.purchase_center import product_routes
from fastapi_app.api.v1.endpoints.purchase_center.schemas import BomCopyRequest
from fastapi_app.core.redis_wrapper import safe_get, safe_set
from fastapi_app.schemas.purchase_center import BomSaveRequest


@pytest.fixture
def fallback_cache(monkeypatch):
    from utils.redis_cache import redis_cache

    monkeypatch.setattr(redis_cache, 'redis_client', None)
    monkeypatch.setattr(redis_cache, 'key_prefix', 'erp:')
    redis_cache._fallback_cache.clear()
    redis_cache._fallback_timestamps.clear()
    yield redis_cache
    redis_cache._fallback_cache.clear()
    redis_cache._fallback_timestamps.clear()


@asynccontextmanager
async def _fake_tx(_db):
    yield


async def test_save_bom_clears_purchase_products_cache(fallback_cache, monkeypatch):
    await safe_set('purchase:products:p1:pp50', {'items': []}, timeout=60)
    assert await safe_get('purchase:products:p1:pp50') is not None

    events: list = []

    @asynccontextmanager
    async def _ordered_tx(_db):
        events.append('tx_enter')
        yield
        events.append('tx_commit')

    original_invalidate = product_routes.cache_mgr.invalidate

    async def record_invalidate(strategy, target):
        events.append(('invalidate', strategy, target))
        return await original_invalidate(strategy, target)

    monkeypatch.setattr(
        product_routes.svc, 'save_product_bom', AsyncMock(return_value='ok'),
    )
    monkeypatch.setattr(
        product_routes, 'schedule_bom_saved_side_effects', MagicMock(),
    )
    monkeypatch.setattr(product_routes, 'db_transaction', _ordered_tx)
    monkeypatch.setattr(product_routes.cache_mgr, 'invalidate', record_invalidate)

    await product_routes.api_save_product_bom(
        1, BomSaveRequest(), db=object(),
        _current_user=SimpleNamespace(username='tester'),
    )

    assert await safe_get('purchase:products:p1:pp50') is None
    first_invalidate = next(i for i, e in enumerate(events) if isinstance(e, tuple))
    assert events.index('tx_commit') < first_invalidate, (
        '缓存失效必须发生在事务提交之后（M-6）'
    )


async def test_copy_bom_clears_purchase_products_cache(fallback_cache, monkeypatch):
    await safe_set('purchase:products:p2:pp50', {'items': []}, timeout=60)

    monkeypatch.setattr(
        product_routes.svc, 'copy_bom_to_product',
        AsyncMock(return_value={'message': 'ok'}),
    )
    monkeypatch.setattr(
        product_routes, 'schedule_bom_saved_side_effects', MagicMock(),
    )
    monkeypatch.setattr(product_routes, 'db_transaction', _fake_tx)

    await product_routes.api_copy_bom_to_product(
        2, BomCopyRequest(source_product_id=1), db=object(),
        _current_user=SimpleNamespace(username='tester'),
    )

    assert await safe_get('purchase:products:p2:pp50') is None
