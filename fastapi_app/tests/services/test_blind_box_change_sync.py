"""盲盒配置变更后的 pending 单强制重算：接线与失败隔离。

覆盖：
1. 提交后回调走独立会话 + 事务，调用同步时带 ``force_quantity_from_bom=True``；
2. 产品无 BOM 时跳过（空目标会删光明细）；
3. 同步失败只记日志，不影响产品保存；
4. 调度器只在 post-commit 阶段执行。
"""
import logging
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from fastapi_app.core.exceptions import run_post_commit_callbacks
from fastapi_app.services.purchase import _auto_generate as hook

_FACTORY = 'fastapi_app.core.database.require_async_session_local'
_TRANSACTION = 'fastapi_app.core.exceptions.db_transaction'
_HAS_BOM = 'fastapi_app.services.purchase.bom_sync.product_has_bom'
_SYNC = 'fastapi_app.services.purchase.bom_sync.sync_pending_items_for_product'


class _SessionCM:
    def __init__(self, db):
        self._db = db

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, *exc):
        return False


class _FakeSessionFactory:
    def __init__(self):
        self.sessions = []

    def __call__(self):
        db = AsyncMock()
        self.sessions.append(db)
        return _SessionCM(db)


@pytest.fixture
def wiring(monkeypatch):
    calls = []
    factory = _FakeSessionFactory()

    @asynccontextmanager
    async def fake_transaction(db):
        calls.append(('transaction', db))
        yield

    async def fake_has_bom(_db, _pid):
        return True

    async def fake_sync(db, product_id, **kwargs):
        calls.append(('sync', db, product_id, kwargs))
        return {'synced': 1, 'skipped': 0, 'unresolved_po_ids': [], 'results': [object()]}

    async def fake_invalidate():
        calls.append(('invalidate',))

    monkeypatch.setattr(_FACTORY, lambda: factory)
    monkeypatch.setattr(_TRANSACTION, fake_transaction)
    monkeypatch.setattr(_HAS_BOM, fake_has_bom)
    monkeypatch.setattr(_SYNC, fake_sync)
    monkeypatch.setattr(hook, 'invalidate_purchase_caches', fake_invalidate)
    return calls, factory


async def test_blind_box_change_runs_forced_sync(wiring):
    calls, factory = wiring

    await hook._run_blind_box_changed(42)

    sync_call = next(c for c in calls if c[0] == 'sync')
    assert sync_call[2] == 42
    assert sync_call[3] == {'force_quantity_from_bom': True}
    assert any(c[0] == 'invalidate' for c in calls)
    assert len(factory.sessions) == 1


async def test_blind_box_change_skips_sync_when_no_bom(wiring, monkeypatch):
    calls, _factory = wiring

    async def no_bom(_db, _pid):
        return False

    monkeypatch.setattr(_HAS_BOM, no_bom)
    await hook._run_blind_box_changed(42)

    assert not any(c[0] == 'sync' for c in calls)
    assert any(c[0] == 'invalidate' for c in calls)


async def test_blind_box_change_failure_is_swallowed(wiring, monkeypatch, caplog):
    _calls, _factory = wiring

    async def boom(_db, _pid, **_kwargs):
        raise RuntimeError('sync down')

    monkeypatch.setattr(_SYNC, boom)
    with caplog.at_level(logging.WARNING):
        await hook._run_blind_box_changed(42)  # 不抛异常即通过

    assert '盲盒配置变更后同步采购明细失败' in caplog.text


async def test_scheduler_runs_on_post_commit(wiring):
    calls, _factory = wiring
    db = AsyncMock()
    db.info = {}

    hook.schedule_blind_box_changed_side_effects(db, 42)
    assert len(db.info['post_commit_callbacks']) == 1
    assert not any(c[0] == 'sync' for c in calls), '注册阶段不得执行'

    await run_post_commit_callbacks(db)

    sync_call = next(c for c in calls if c[0] == 'sync')
    assert sync_call[2] == 42
    assert sync_call[3] == {'force_quantity_from_bom': True}
