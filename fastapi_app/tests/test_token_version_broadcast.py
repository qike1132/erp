"""M-23 回归：bump_token_version 跨 worker 广播（2026-11-21 全量审计）。

改密/禁用后 bump_token_version 只失效本进程 _USER_ACTIVE_CACHE（TTL 10s），
其他 worker 最长 10s 内仍按旧 token_version 放行被吊销会话；权限缓存有
USER_PERMISSION_CHANGED 跨 worker 广播兜底而会话版本没有。修复：post-commit
发布同一事件（订阅器同时清权限与活跃两个缓存，deps.py:103-111）。
"""
import types

import pytest

from fastapi_app.services import user_service


@pytest.mark.asyncio
async def test_bump_schedules_permission_changed_broadcast(monkeypatch):
    scheduled = []
    published = []

    def _fake_schedule(session, callback):
        scheduled.append(callback)
        return True

    async def _fake_publish(event):
        published.append(event)

    monkeypatch.setattr(
        'fastapi_app.core.domain_events.schedule_post_commit_callback', _fake_schedule)
    monkeypatch.setattr('fastapi_app.core.domain_events.publish', _fake_publish)

    user = types.SimpleNamespace(id=5, token_version=3)

    class _FakeSession:
        async def flush(self):
            return None

    await user_service.bump_token_version(_FakeSession(), user)

    assert user.token_version == 4
    assert len(scheduled) == 1, '修复前不调度跨 worker 广播（Red 断言点）'
    # 模拟事务提交后执行回调
    await scheduled[0]()
    assert len(published) == 1
    event = published[0]
    assert event.event_type.value == 'user.permission_changed'
    assert event.payload == {'user_id': 5}
