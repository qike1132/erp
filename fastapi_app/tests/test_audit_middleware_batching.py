"""P1-9：审计写入移出请求热路径（每请求一次批量写入）回归测试

覆盖：
1. 单请求产生多条审计事件时，降级直写只发生一次 session.execute（单条多行 INSERT）；
2. Redis 缓冲可用时整批走队列，请求内 0 次写库；
3. 审计写库失败时主请求仍返回原状态码（直写失败 / 投递整体异常两条路径）；
4. 内容不丢：同请求的多条事件全部在同一条 INSERT 的绑定参数里；
5. `flush_audit_buffer` 批量落库同样是 1 次 execute（原实现循环内逐条 execute）。
"""
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from starlette.requests import Request
from starlette.responses import Response

from fastapi_app.core import audit_middleware as am

# conftest 的 autouse fixture 会在测试运行期把 _write_audit_direct 换成 no-op
# （避免测试进程建立真实 asyncpg 连接）。本模块需要真实实现来断言「整批一次 execute」，
# 故在导入期留一份真身引用，测试内临时恢复。
_REAL_WRITE_AUDIT_DIRECT = am._write_audit_direct


def _make_request(path: str = '/api/v1/orders', method: str = 'POST') -> Request:
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


class _RecordingSession:
    """记录 session.execute 次数/参数与 commit 次数的最小替身"""

    def __init__(self, record: dict, *, fail: bool = False):
        self._record = record
        self._fail = fail

    async def execute(self, statement, params=None):
        if self._fail:
            raise RuntimeError('db down')
        self._record['executes'].append((str(statement), params))

    async def commit(self):
        self._record['commits'] += 1

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


class _RecordingSessionFactory:
    def __init__(self, record: dict, *, fail: bool = False):
        self._record = record
        self._fail = fail
        self.opens = 0

    def __call__(self):
        self.opens += 1
        return _RecordingSession(self._record, fail=self._fail)


async def _call_next_with_denial(request: Request) -> Response:
    """模拟写请求：依赖层先记一条 403 拒绝审计，中间件的写审计再补一条 → 同请求 2 条"""
    request.state.user_id = 7
    request.state.username = 'u7'
    await am.record_access_denied(
        request, None, required_permissions=('order_manage',), reason='missing_permission',
    )
    return Response(status_code=403)


@pytest.mark.asyncio
async def test_single_request_multiple_entries_uses_one_execute():
    """验收 1+3：单请求 2 条审计 → 1 次 session.execute / 1 次 commit，两条都在同一条 INSERT 里"""
    record: dict = {'executes': [], 'commits': 0}
    factory = _RecordingSessionFactory(record)

    with patch.object(am, '_get_audit_session_factory', lambda: factory), \
            patch.object(am, '_write_audit_direct', _REAL_WRITE_AUDIT_DIRECT), \
            patch('fastapi_app.core.redis_wrapper.safe_rpush', AsyncMock(return_value=0)), \
            patch('fastapi_app.core.redis_wrapper.safe_llen', AsyncMock(return_value=0)):
        response = await am.AuditLogMiddleware(app=None).dispatch(
            _make_request(), _call_next_with_denial,
        )

    assert response.status_code == 403
    assert factory.opens == 1, '同请求应只开一次事务'
    assert len(record['executes']) == 1, '单请求多条审计日志的 DB execute 次数应为 1'
    assert record['commits'] == 1
    sql, params = record['executes'][0]
    assert sql.count('(:user_id_') == 2, '两条事件应在同一条多行 INSERT 中'
    assert {params['action_0'], params['action_1']} == {am.ACCESS_DENIED_ACTION, 'CREATE'}
    assert params['request_id_0'] == params['request_id_1'], '两条事件属于同一请求'


@pytest.mark.asyncio
async def test_redis_queue_path_performs_no_db_write():
    """验收 1 的「或走队列」分支：Redis 可用时整批入队，请求内不碰数据库"""
    record: dict = {'executes': [], 'commits': 0}
    factory = _RecordingSessionFactory(record)
    pushed: list = []

    async def _rpush(key, *values, context=''):
        pushed.extend(values)
        return len(pushed)

    with patch.object(am, '_get_audit_session_factory', lambda: factory), \
            patch.object(am, '_write_audit_direct', _REAL_WRITE_AUDIT_DIRECT), \
            patch('fastapi_app.core.redis_wrapper.safe_rpush', _rpush), \
            patch('fastapi_app.core.redis_wrapper.safe_llen', AsyncMock(return_value=2)):
        response = await am.AuditLogMiddleware(app=None).dispatch(
            _make_request(), _call_next_with_denial,
        )

    assert response.status_code == 403
    assert len(pushed) == 2, '同请求两条事件都应入队'
    payloads = [json.loads(item) for item in pushed]
    assert [item['action'] for item in payloads] == ['ACCESS_DENIED', 'CREATE']
    # created_at（datetime）必须能被 JSON 序列化：原实现漏了 default=str，
    # 导致 json.dumps 抛 TypeError → 每次都跌进 except 直写，缓冲路径形同虚设
    assert all(isinstance(item['created_at'], str) for item in payloads)
    assert record['executes'] == [], '走队列时请求内不应有写库'
    assert factory.opens == 0


@pytest.mark.asyncio
async def test_write_failure_keeps_original_status_code():
    """验收 2：审计写库抛错时主请求仍返回原状态码"""
    record: dict = {'executes': [], 'commits': 0}
    factory = _RecordingSessionFactory(record, fail=True)

    async def _call_next(request: Request) -> Response:
        return Response(status_code=201)

    with patch.object(am, '_get_audit_session_factory', lambda: factory), \
            patch.object(am, '_write_audit_direct', _REAL_WRITE_AUDIT_DIRECT), \
            patch('fastapi_app.core.redis_wrapper.safe_rpush', AsyncMock(return_value=0)), \
            patch('fastapi_app.core.redis_wrapper.safe_llen', AsyncMock(return_value=0)):
        response = await am.AuditLogMiddleware(app=None).dispatch(_make_request(), _call_next)

    assert response.status_code == 201
    assert record['commits'] == 0


@pytest.mark.asyncio
async def test_flush_exception_keeps_original_status_code():
    """验收 2：整批投递本身抛异常（含 flush 兜底）也不改变主请求响应"""
    async def _call_next(request: Request) -> Response:
        return Response(status_code=202)

    with patch.object(am, '_buffer_audit_entry', AsyncMock(side_effect=RuntimeError('boom'))):
        response = await am.AuditLogMiddleware(app=None).dispatch(_make_request(), _call_next)

    assert response.status_code == 202


@pytest.mark.asyncio
async def test_flush_buffer_writes_batch_in_single_execute():
    """验收 3：缓冲刷写把整批合并为 1 次 execute（原实现循环内逐条 execute）"""
    record: dict = {'executes': [], 'commits': 0}
    factory = _RecordingSessionFactory(record)
    original_created_at = datetime(2026, 10, 1, 8, 30, 15, tzinfo=UTC)
    raw = [
        json.dumps({
            'user_id': i, 'username': f'u{i}', 'action': 'CREATE', 'resource_type': 'order',
            'resource_id': str(i), 'detail': '{}', 'ip_address': '10.0.0.1',
            'user_agent': 'agent', 'request_id': f'rid-{i}', 'status_code': 200,
            'created_at': original_created_at.isoformat(),
        })
        for i in range(3)
    ]

    with patch.object(am, '_get_audit_session_factory', lambda: factory), \
            patch.object(am, '_write_audit_direct', _REAL_WRITE_AUDIT_DIRECT), \
            patch('fastapi_app.core.redis_wrapper.safe_acquire_lock', AsyncMock(return_value=True)), \
            patch('fastapi_app.core.redis_wrapper.safe_release_lock', AsyncMock(return_value=None)), \
            patch('fastapi_app.core.redis_wrapper.safe_lrange', AsyncMock(return_value=raw)), \
            patch('fastapi_app.core.redis_wrapper.safe_ltrim', AsyncMock(return_value=True)):
        await am.flush_audit_buffer()

    assert len(record['executes']) == 1
    assert record['commits'] == 1
    sql, params = record['executes'][0]
    assert sql.count('(:user_id_') == 3
    assert sorted(params[f'user_id_{i}'] for i in range(3)) == [0, 1, 2]
    # JSON 反序列化丢 datetime 类型 → 必须还原成 datetime，且保留原时间戳（不能被刷写时刻覆盖）
    assert isinstance(params['created_at_0'], datetime)
    assert params['created_at_0'] == original_created_at


@pytest.mark.asyncio
async def test_flush_skips_when_lock_not_acquired():
    """并发保护：抢不到刷写锁时整轮跳过——不读、不写、不裁剪。

    LRANGE + LTRIM 不原子，两个刷写者同时进入会丢数据（后执行的 LTRIM 把从未读到的
    下一段一并裁掉）。跳过只是推迟到下一轮，抢跑才危险。
    """
    record: dict = {'executes': [], 'commits': 0}
    factory = _RecordingSessionFactory(record)
    lrange = AsyncMock(return_value=[json.dumps({'user_id': 1})])
    ltrim = AsyncMock(return_value=True)

    with patch.object(am, '_get_audit_session_factory', lambda: factory), \
            patch.object(am, '_write_audit_direct', _REAL_WRITE_AUDIT_DIRECT), \
            patch('fastapi_app.core.redis_wrapper.safe_acquire_lock', AsyncMock(return_value=False)), \
            patch('fastapi_app.core.redis_wrapper.safe_lrange', lrange), \
            patch('fastapi_app.core.redis_wrapper.safe_ltrim', ltrim):
        await am.flush_audit_buffer()

    assert record['executes'] == [], '未持锁不得写库'
    lrange.assert_not_awaited()
    ltrim.assert_not_awaited()


@pytest.mark.asyncio
async def test_flush_keeps_buffer_when_write_fails():
    """先写库、后裁剪：落库失败时不得裁剪，否则这批条目既不在缓冲也不在库里。"""
    record: dict = {'executes': [], 'commits': 0}
    factory = _RecordingSessionFactory(record, fail=True)
    raw = [json.dumps({'user_id': 1, 'created_at': datetime(2026, 10, 1, 8, 30, tzinfo=UTC).isoformat()})]
    ltrim = AsyncMock(return_value=True)

    with patch.object(am, '_get_audit_session_factory', lambda: factory), \
            patch.object(am, '_write_audit_direct', _REAL_WRITE_AUDIT_DIRECT), \
            patch('fastapi_app.core.redis_wrapper.safe_acquire_lock', AsyncMock(return_value=True)), \
            patch('fastapi_app.core.redis_wrapper.safe_release_lock', AsyncMock(return_value=None)), \
            patch('fastapi_app.core.redis_wrapper.safe_lrange', AsyncMock(return_value=raw)), \
            patch('fastapi_app.core.redis_wrapper.safe_ltrim', ltrim):
        await am.flush_audit_buffer()

    assert record['commits'] == 0, '写入失败不应有提交'
    ltrim.assert_not_awaited()


def test_batch_insert_sql_shape():
    """多行 INSERT 的列顺序/行数与绑定参数自洽（audit_log 表结构锁）"""
    sql, params = am._build_batch_insert([{'user_id': 1}, {'user_id': 2}])
    assert sql.startswith('INSERT INTO audit_log (' + ', '.join(am.AUDIT_LOG_COLUMNS) + ') VALUES ')
    assert sql.count('(:user_id_') == 2
    assert len(params) == 2 * len(am.AUDIT_LOG_COLUMNS)
    assert params['created_at_1'] is None


@pytest.mark.asyncio
async def test_direct_caller_without_request_bucket_still_submits():
    """无请求级收集桶的直接调用方（如 backup/export.py）仍走单条管线"""
    captured: list = []

    async def _capture(entry: dict) -> None:
        captured.append(entry)

    entry = {'user_id': 1, 'action': 'EXPORT'}
    with patch.object(am, '_buffer_audit_entry', _capture):
        await am._submit_audit_entry(_make_request(method='GET'), entry)

    assert captured == [entry]
