"""ORDER_DELETED 兜底清理的事务隔离回归（2026-10-30 审计 A-M18）。

原实现把「SKU 快照主清理」和「无快照存量单兜底清理」放在**同一个会话/事务**里：
兜底那步抛错会把主清理一起回滚，而外层只记一条日志 —— 结果订单删了、引用它的
pending 采购单仍在，且没有任何痕迹。

修复后兜底走独立事务并单独 try/except：主清理已提交，兜底失败只告警。
本文件锁定这三点：
1. 兜底与主清理使用不同会话；
2. 兜底失败不抛出、也不影响缓存失效；
3. 主清理失败**必须冒泡**（2026-11-17 上线前审计 V-27 改）：事件 handler 的失败由
   ``domain_events._dispatch_in_process`` 记 ``stage=handler`` 死信；handler 自己吞掉
   就等于「撤销失败不留证据」。handler 之间的隔离仍由 dispatcher 保证。
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.services import purchase_center_service as svc


class _Ctx:
    """async contextmanager 替身，记录自己是第几个会话。"""

    def __init__(self, sessions, label):
        self.sessions = sessions
        self.label = label

    async def __aenter__(self):
        self.sessions.append(self.label)
        return MagicMock(name=f'db-{self.label}')

    async def __aexit__(self, *exc):
        return False


def _capture_handler(sessions: list[str]):
    """注册一次订阅，取出 ORDER_DELETED 处理器。

    `get_async_db_context` 是在**注册时**被闭包捕获的，所以替身必须在注册前注入
    （注册后再 patch core.database 不会影响已捕获的引用）。
    """
    captured: dict = {}
    labels = iter(['main', 'fallback'])

    def _ctx():
        return _Ctx(sessions, next(labels, 'extra'))

    def _fake_subscribe(event_type, handler):
        captured['event_type'] = event_type
        captured['handler'] = handler

    with patch('fastapi_app.core.database.get_async_db_context', side_effect=_ctx) as m_ctx, \
         patch.object(svc, 'subscribe', side_effect=_fake_subscribe):
        svc._register_order_event_subscriptions()

    captured['ctx'] = m_ctx
    return captured


@pytest.mark.asyncio
async def test_fallback_cleanup_uses_separate_session_and_swallow_failure():
    sessions: list[str] = []
    cap = _capture_handler(sessions)
    handler = cap['handler']

    event = MagicMock()
    event.payload = {'order_id': 42}

    # 返回值按真实形状给：V-27 起 handler 会读 failed_po_ids（裸 AsyncMock 返回 MagicMock
    # → 会被误判成「部分失败」）
    with patch('fastapi_app.services.purchase_order_revoke.revoke_pending_purchase_orders_for_order',
               new=AsyncMock(return_value={'revoked': 1, 'orders_reset': 0})) as m_revoke, \
         patch.object(svc, 'cleanup_orphan_pending_purchase_orders',
                      new=AsyncMock(side_effect=RuntimeError('boom'))) as m_cleanup, \
         patch('fastapi_app.services.purchase._auto_generate.invalidate_purchase_caches',
               new=AsyncMock()) as m_invalidate:
        await handler(event)

    # 两个独立会话：主清理 + 兜底
    assert cap['ctx'].call_count == 2
    assert sessions == ['main', 'fallback']
    m_revoke.assert_awaited_once()
    assert m_revoke.await_args.args[1] == 42
    m_cleanup.assert_awaited_once()
    assert m_cleanup.await_args.args[1] == [42]
    # 兜底失败后仍要失效缓存（否则已删采购单会存活到 TTL）
    m_invalidate.assert_awaited_once()


@pytest.mark.asyncio
async def test_main_cleanup_failure_propagates_to_dispatcher():
    """主清理失败必须冒泡（2026-11-17 上线前审计 V-27）。

    与本文件 A-M18 的口径不冲突：**兜底清理**失败仍只告警（上面那条用例），但
    **主清理**（撤销引用订单的 pending 采购单）失败是这次事件的全部意义，必须让
    dispatcher 记 ``stage=handler`` 死信 —— 否则「撤销失败」在证据上等于成功
    （AGENTS §6.1-9）。handler 之间的隔离由 ``_dispatch_in_process`` 的逐 handler
    try/except 保证，不需要 handler 自己把异常吞掉。
    """
    sessions: list[str] = []
    cap = _capture_handler(sessions)
    handler = cap['handler']

    event = MagicMock()
    event.payload = {'order_id': 7}

    with patch('fastapi_app.services.purchase_order_revoke.revoke_pending_purchase_orders_for_order',
               new=AsyncMock(side_effect=RuntimeError('db down'))), \
         patch.object(svc, 'cleanup_orphan_pending_purchase_orders', new=AsyncMock()) as m_cleanup:
        with pytest.raises(RuntimeError):
            await handler(event)

    # 主清理失败后不再执行兜底
    assert cap['ctx'].call_count == 1
    m_cleanup.assert_not_awaited()


@pytest.mark.asyncio
async def test_handler_ignores_event_without_order_id():
    sessions: list[str] = []
    cap = _capture_handler(sessions)
    handler = cap['handler']

    event = MagicMock()
    event.payload = {}

    await handler(event)

    assert cap['ctx'].call_count == 0


@pytest.mark.asyncio
async def test_partial_revocation_failure_lands_in_handler_deadletter(tmp_path, monkeypatch):
    """部分撤销失败（``failed_po_ids`` 非空）必须进死信，且带 stage=handler（V-27）。

    ``_revoke_targets`` 早就把删不掉的单单独放在 ``failed_po_ids`` 返回，但此前
    handler 直接丢弃 —— 死信文件里永远没有痕迹。本用例走真实 dispatcher
    （``_dispatch_in_process``），断言死信记录里能看到 po_ids，可供人工/脚本按 id 重试。
    """
    from fastapi_app.core import domain_events as de

    monkeypatch.setenv('ERP_DEADLETTER_DIR', str(tmp_path))
    monkeypatch.setattr(de, '_subscribers', {})

    cap = _capture_handler([])
    de.subscribe(de.DomainEventType.ORDER_DELETED, cap['handler'])

    event = de.DomainEvent(
        event_type=de.DomainEventType.ORDER_DELETED, domain='order',
        payload={'order_id': 42},
    )
    partial = {'revoked': 1, 'orders_reset': 0, 'failed_po_ids': [11, 12]}
    with patch('fastapi_app.services.purchase_order_revoke.revoke_pending_purchase_orders_for_order',
               new=AsyncMock(return_value=partial)), \
         patch.object(svc, 'cleanup_orphan_pending_purchase_orders', new=AsyncMock()):
        await de._dispatch_in_process(event)

    deadletter = tmp_path / 'domain_events_deadletter.jsonl'
    assert deadletter.exists(), '部分撤销失败没有落死信 —— 失败仍被静默吞掉'
    records = [json.loads(line) for line in deadletter.read_text(encoding='utf-8').splitlines() if line.strip()]
    assert len(records) == 1, records
    assert records[0]['stage'] == 'handler', records[0]
    assert records[0]['event_type'] == de.DomainEventType.ORDER_DELETED.value
    assert 'po_ids=[11, 12]' in records[0]['error'], records[0]['error']
    assert records[0]['error_type'] == 'PartialRevocationError', records[0]
