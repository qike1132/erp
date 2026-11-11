"""BOM 保存后置副作用：撤销（若删空）→ 同步 pending 采购明细 → 自动生成（task-5）。

锁死不变量：
1. 顺序固定：revoke → sync → generate（撤销先行，删空的产品不会被「按空 BOM 重建」）；
2. sync 走**独立会话** + ``db_transaction``，入参为 (db, product_id)，非 dry-run；
3. sync 失败只记日志，不阻断后续自动生成（BOM 保存本身更不受影响）；
4. revoke 失败同样不阻断 sync / generate。
"""
import logging
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from fastapi_app.services.purchase import _auto_generate as hook

_FACTORY = 'fastapi_app.core.database.require_async_session_local'
_TRANSACTION = 'fastapi_app.core.exceptions.db_transaction'
_REVOKE = (
    'fastapi_app.services.purchase_order_revoke.revoke_pending_purchase_orders_for_product'
)
_SYNC = 'fastapi_app.services.purchase.bom_sync.sync_pending_items_for_product'
_HAS_BOM = 'fastapi_app.services.purchase.bom_sync.product_has_bom'


class _SessionCM:
    def __init__(self, db):
        self._db = db

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, *exc):
        return False


class _FakeSessionFactory:
    """每次调用返回一个新假会话；记录创建顺序，以断言 revoke/sync 不共用会话。"""

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

    async def fake_revoke(db, product_id):
        calls.append(('revoke', db, product_id))
        return {'revoked': 0, 'orders_reset': 0}

    async def fake_has_bom(_db, _product_id):
        return True

    async def fake_sync(db, product_id, **kwargs):
        calls.append(('sync', db, product_id, kwargs))
        return {'synced': 1, 'skipped': 0, 'unresolved_po_ids': [],
                'results': [object()]}

    async def fake_generate(*_a, **_k):
        calls.append(('generate',))

    monkeypatch.setattr(_FACTORY, lambda: factory)
    monkeypatch.setattr(_TRANSACTION, fake_transaction)
    monkeypatch.setattr(_REVOKE, fake_revoke)
    monkeypatch.setattr(_HAS_BOM, fake_has_bom)
    monkeypatch.setattr(_SYNC, fake_sync)
    monkeypatch.setattr(hook, '_run_auto_generate', fake_generate)
    return calls, factory


def _steps(calls):
    return [c[0] for c in calls if c[0] != 'transaction']


async def test_bom_save_runs_revoke_sync_then_generate(wiring):
    """顺序固定：撤销 → 同步 → 自动生成。"""
    calls, _factory = wiring

    await hook._run_bom_saved(42)

    assert _steps(calls) == ['revoke', 'sync', 'generate'], f'顺序错: {_steps(calls)}'


async def test_sync_uses_independent_session_and_plain_call(wiring):
    """sync 在独立会话 + 独立事务里执行；入参 (db, product_id)，不带 dry_run。"""
    calls, factory = wiring

    await hook._run_bom_saved(42)

    assert len(factory.sessions) == 2, 'revoke 与 sync 应各开一个独立会话'
    revoke_db, sync_db = factory.sessions
    assert revoke_db is not sync_db

    transactions = [c for c in calls if c[0] == 'transaction']
    assert [c[1] for c in transactions] == [revoke_db, sync_db], '每步都须过 db_transaction'
    # 事务先于该步的写入调用
    assert calls.index(('transaction', revoke_db)) < calls.index(('revoke', revoke_db, 42))
    assert calls.index(('transaction', sync_db)) < calls.index(('sync', sync_db, 42, {}))

    sync_call = next(c for c in calls if c[0] == 'sync')
    assert sync_call[2] == 42
    assert sync_call[3] == {}, f'sync 不应带额外参数: {sync_call[3]}'


async def test_sync_failure_is_swallowed_and_generate_still_runs(
    wiring, monkeypatch, caplog,
):
    """同步失败只记日志：不冒泡，自动生成照常跑。"""
    calls, _factory = wiring

    async def boom_sync(_db, _product_id):
        calls.append(('sync',))
        raise RuntimeError('sync down')

    monkeypatch.setattr(_SYNC, boom_sync)

    with caplog.at_level(logging.WARNING):
        await hook._run_bom_saved(42)  # 不抛异常即通过

    assert _steps(calls) == ['revoke', 'sync', 'generate']
    assert 'BOM 变更同步采购明细失败' in caplog.text


async def test_revoke_failure_does_not_block_sync_and_generate(
    wiring, monkeypatch, caplog,
):
    """撤销失败同样 best-effort：不阻断同步与自动生成。"""
    calls, _factory = wiring

    async def boom_revoke(_db, _product_id):
        calls.append(('revoke',))
        raise RuntimeError('revoke down')

    monkeypatch.setattr(_REVOKE, boom_revoke)

    with caplog.at_level(logging.WARNING):
        await hook._run_bom_saved(42)

    assert _steps(calls) == ['revoke', 'sync', 'generate']
    assert '撤销采购单失败' in caplog.text


async def test_empty_bom_skips_sync_so_pending_items_are_not_wiped(
    wiring, monkeypatch, caplog,
):
    """BOM 已删空 → 不调用同步（否则条码回退命中的单会被按空 BOM 删光明细）。

    评审 Important：撤销层按名称回退解析、撤不掉的单（备货一键生成 + 产品改名），
    同步层凭条码回退仍会命中；若此时 BOM 已空，目标行集合为空会整单删光明细并留下
    0 明细 pending 单。守卫必须针对本次保存的 product_id。
    """
    calls, _factory = wiring
    guarded = []

    async def no_bom(db, product_id):
        guarded.append((db, product_id))
        return False

    monkeypatch.setattr(_HAS_BOM, no_bom)

    with caplog.at_level(logging.INFO):
        await hook._run_bom_saved(42)

    assert _steps(calls) == ['revoke', 'generate'], f'BOM 空时不得同步: {_steps(calls)}'
    assert [pid for _db, pid in guarded] == [42], '守卫必须针对本次保存的产品'
    assert 'BOM 已删空，跳过采购明细同步' in caplog.text
