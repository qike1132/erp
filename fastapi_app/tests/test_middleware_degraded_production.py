"""P0-10：安全降级登记机制 + /api/health 可观测性（死分支删除后的口径）。

背景（captain 2026-10-01 裁决，逐字节核查）：原实现里 conditional_csrf_middleware 的
`if _is_production and CSRF_DEGRADED_ITSDANGEROUS in degraded_reasons(): ... 503` 判定
与 _setup_csrf 的 `except ImportError` 分支都**不可达** —— fastapi_app/** 内 0 处
itsdangerous import，_setup_csrf 的 try 体内只 import ipaddress / secrets（标准库），
CSRF token 由 secrets.token_urlsafe 生成。故死分支连同常量 CSRF_DEGRADED_ITSDANGEROUS
一并删除（本文件锁定删除结果，防回归）：

1. record_degradation / degraded_reasons / clear_degradations 机制本身保留（通用登记口）；
2. 生产环境不再因「登记了降级原因」而 503 —— 登记 ≠ 拒绝服务；
3. /api/health 通过 degraded / security_degraded 暴露降级，但**不**把状态码改成 503；
4. _setup_csrf 内不得再出现 except ImportError 死分支与 CSRF_DEGRADED 常量引用。
"""
import inspect
import logging

import pytest

import fastapi_app.core.middleware as middleware_mod
from fastapi_app.core.health import _with_security_degraded
from fastapi_app.core.middleware import (
    clear_degradations,
    degraded_reasons,
    record_degradation,
)

_REASON = 'test_degradation_reason'


@pytest.fixture(autouse=True)
def _isolate_degradation_state():
    """降级登记是进程级状态：每个用例前后都要清干净，避免污染其它测试。"""
    clear_degradations()
    yield
    clear_degradations()


def test_record_degradation_is_idempotent():
    record_degradation(_REASON)
    record_degradation(_REASON)
    assert degraded_reasons() == [_REASON]


def test_degraded_reasons_returns_a_copy():
    record_degradation(_REASON)
    snapshot = degraded_reasons()
    snapshot.append('tampered')
    assert degraded_reasons() == [_REASON]


def test_health_payload_marks_degradation_without_changing_status():
    payload = {'status': 'healthy', 'app': 'x'}
    marked = _with_security_degraded(payload)
    assert marked['status'] == 'healthy', '降级不得改变既有状态字段'
    assert marked['security_degraded'] is False and marked['degraded'] == []
    assert payload == {'status': 'healthy', 'app': 'x'}, '不得就地修改入参'

    record_degradation(_REASON)
    marked = _with_security_degraded(payload)
    assert marked['status'] == 'healthy'
    assert marked['security_degraded'] is True
    assert marked['degraded'] == [_REASON]


@pytest.mark.asyncio
async def test_health_endpoint_exposes_degradation_with_status_200(client):
    """/api/health 必须暴露降级标记，且状态码保持 200（降级≠服务不可用）。"""
    record_degradation(_REASON)
    resp = await client.get('/api/health')
    assert resp.status_code == 200, f'降级不应把健康检查打成 503: {resp.status_code}'
    body = resp.json()
    assert body['security_degraded'] is True
    assert _REASON in body['degraded']


def _code_of(func) -> str:
    """去掉注释/空行后的函数源码，用于「死分支不得回潮」的守卫断言。"""
    lines = [ln for ln in inspect.getsource(func).splitlines()]
    return "\n".join(ln for ln in lines if ln.strip() and not ln.lstrip().startswith('#'))


def test_csrf_setup_has_no_dead_itsdangerous_branch():
    """死分支删除的守卫：_setup_csrf 内不得回潮（注释里的历史说明不算实现）。"""
    code = _code_of(middleware_mod._setup_csrf)
    assert 'except ImportError' not in code, '不可达的 except ImportError 死分支回潮'
    assert 'CSRF_DEGRADED' not in code, '已删除的 CSRF 降级常量被重新引用'
    assert not hasattr(middleware_mod, 'CSRF_DEGRADED_ITSDANGEROUS'), '常量应已删除'


@pytest.mark.asyncio
async def test_production_write_is_not_blocked_by_recorded_degradation(client, monkeypatch, caplog):
    """登记了降级原因也不得让生产写请求 503（旧 fail-closed 分支已按裁决删除）。

    刻意发一个**校验必然失败**的写请求（空 body → 422）：路由前的 CSRF 中间件若还带
    旧 503 短路，这里拿到的就是 503；分支删除后请求会一路走到 FastAPI 参数校验，
    因此不会触碰 DB 依赖（不引入无关的 mock 依赖）。
    """
    record_degradation(_REASON)
    monkeypatch.setenv('APP_ENV', 'production')
    with caplog.at_level(logging.ERROR, logger='fastapi_app.core.middleware'):
        resp = await client.post('/api/v1/auth/login')
    assert resp.status_code != 503, f'降级仍误拦写请求: {resp.status_code} {resp.text[:200]}'
    assert resp.status_code == 422, f'请求未走到参数校验（说明仍被中间件短路）: {resp.status_code}'
    assert '安全降级' not in resp.text
    assert not any('安全降级' in rec.getMessage() for rec in caplog.records), '已删除的降级日志文案回潮'
