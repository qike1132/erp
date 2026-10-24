"""AUD-07（2026-10-24 审计）回归锁：审计条目的 request_id 与 X-Request-ID 同源。

原先 AuditLogMiddleware（最外层）在 dispatch 进入时自产 request_id，而
request_id 中间件在内层、call_next 返回后才写入 state——写审计
主条目与 access_denied 条目各自取值时机不同，与响应头恒为两个不同值，
「客户端—日志—审计」对账链路全断。

修复后（本文件锁定）：
1. 写审计主条目用 call_next 返回后重读的最终值；
2. 桶内条目（含早于内层写入时刻入桶的）在投递前统一覆写为最终值；
3. 内层未写 state（如中间件顺序变化/直连调用）时回退自产 id，行为不回退。

pytest-asyncio auto 模式：测试即协程，直接 await 被测协程（不得 asyncio.run）。
"""
from unittest.mock import MagicMock

import pytest
from starlette.requests import Request
from starlette.responses import Response

from fastapi_app.core import audit_middleware as am


def _make_request(method: str = 'POST', path: str = '/api/v1/orders') -> Request:
    return Request({
        'type': 'http',
        'method': method,
        'path': path,
        'query_string': b'',
        'headers': [(b'user-agent', b'pytest-agent')],
        'client': ('10.0.0.9', 1234),
        'server': ('test', 80),
        'scheme': 'http',
    })


async def test_flush_overwrites_bucket_ids_with_final_request_id():
    """桶内条目（含外层自产 id）在投递前统一覆写为 state 的最终值。

    两条 pending 走批量管线、单条走单条管线——两路都打桩，断言覆写后到达投递层。
    """
    flushed_single = []
    flushed_batch = []

    async def _capture_single(entry):
        flushed_single.append(entry)

    async def _capture_batch(entries):
        flushed_batch.extend(entries)

    request = _make_request()
    request.state.audit_pending_entries = [
        {'request_id': 'outer-aaa', 'action': 'create', 'user_id': 1},
        {'request_id': 'outer-aaa', 'action': 'access_denied', 'user_id': 1},
    ]
    # 模拟内层 request_id 中间件在 call_next 后写入的最终值
    request.state.request_id = 'inner-123'
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(am, '_buffer_audit_entry', _capture_single)
        mp.setattr(am, '_buffer_audit_entries', _capture_batch)
        await am._flush_request_audit_entries(request)
    assert [e['request_id'] for e in flushed_batch] == ['inner-123', 'inner-123'], (
        '桶内条目必须在投递前统一覆写为最终 request_id（AUD-07）'
    )
    assert flushed_single == []

    # 单条路径同验证
    request2 = _make_request()
    request2.state.audit_pending_entries = [
        {'request_id': 'outer-bbb', 'action': 'create', 'user_id': 1},
    ]
    request2.state.request_id = 'inner-777'
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(am, '_buffer_audit_entry', _capture_single)
        mp.setattr(am, '_buffer_audit_entries', _capture_batch)
        await am._flush_request_audit_entries(request2)
    assert [e['request_id'] for e in flushed_single] == ['inner-777']


async def test_dispatch_records_audit_with_inner_request_id():
    """写方法：_record_audit 收到 call_next 返回后 state 里的最终 request_id。"""
    captured = {}

    async def call_next(request):
        # 内层 request_id 中间件的时序：call_next 内部写 state
        request.state.request_id = 'inner-456'
        return Response(status_code=200)

    request = _make_request()
    request.state.audit_pending_entries = []

    async def _fake_record(self, request_, response, request_id, duration_ms):
        captured['request_id'] = request_id

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(am.AuditLogMiddleware, '_record_audit', _fake_record)
        await am.AuditLogMiddleware(app=MagicMock()).dispatch(request, call_next)

    assert captured['request_id'] == 'inner-456', (
        '写审计主条目必须用内层写入的最终 request_id（AUD-07）'
    )


async def test_dispatch_falls_back_to_self_generated_id():
    """内层未写 state（顺序变化/直连调用）时回退自产 id，行为不回退。"""
    captured = {}

    async def call_next(request):
        return Response(status_code=200)

    request = _make_request()
    request.state.audit_pending_entries = []

    async def _fake_record(self, request_, response, request_id, duration_ms):
        captured['request_id'] = request_id

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(am.AuditLogMiddleware, '_record_audit', _fake_record)
        await am.AuditLogMiddleware(app=MagicMock()).dispatch(request, call_next)

    assert captured['request_id'], '回退路径仍必须有 request_id'
    assert captured['request_id'] != 'inner-456'
