"""ORDER_DELETED 兜底清理的事务隔离回归（2026-10-30 审计 A-M18）。

原实现把「SKU 快照主清理」和「无快照存量单兜底清理」放在**同一个会话/事务**里：
兜底那步抛错会把主清理一起回滚，而外层只记一条日志 —— 结果订单删了、引用它的
pending 采购单仍在，且没有任何痕迹。

修复后兜底走独立事务并单独 try/except：主清理已提交，兜底失败只告警。
本文件锁定这三点：
1. 兜底与主清理使用不同会话；
2. 兜底失败不抛出、也不影响缓存失效；
3. 主清理失败仍被外层兜住（不冒泡到订单删除主流程）。
"""
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

    with patch('fastapi_app.services.purchase_order_revoke.revoke_pending_purchase_orders_for_order',
               new=AsyncMock()) as m_revoke, \
         patch.object(svc, 'cleanup_orphan_pending_purchase_orders',
                      new=AsyncMock(side_effect=RuntimeError('boom'))) as m_cleanup, \
         patch('fastapi_app.services.purchase._auto_generate.invalidate_purchase_caches',
               new=AsyncMock()) as m_invalidate:
        await handler(event)

    # 两个独立会话：主清理 + 兜底
    assert cap['ctx'].call_count == 2
    assert sessions == ['main', 'fallback']
    m_revoke.assert_awaited_once()
    m_cleanup.assert_awaited_once()
    # 兜底失败后仍要失效缓存（否则已删采购单会存活到 TTL）
    m_invalidate.assert_awaited_once()


@pytest.mark.asyncio
async def test_main_cleanup_failure_does_not_propagate():
    sessions: list[str] = []
    cap = _capture_handler(sessions)
    handler = cap['handler']

    event = MagicMock()
    event.payload = {'order_id': 7}

    with patch('fastapi_app.services.purchase_order_revoke.revoke_pending_purchase_orders_for_order',
               new=AsyncMock(side_effect=RuntimeError('db down'))), \
         patch.object(svc, 'cleanup_orphan_pending_purchase_orders', new=AsyncMock()) as m_cleanup:
        await handler(event)  # 不抛

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
