"""登录账户级失败锁定（username 维度）单测。

背景：`api_login` 此前只有 **IP** 维度限流（`login_attempt:{ip}` / `login_burst:{ip}`），
`authenticate_login` 失败时抛 401，但没有任何 username 维度的失败计数 —— 换 IP 即可
对同一账号无限喷洒口令。

本文件覆盖新增的计数窗口（`LOGIN_USER_FAIL_LIMIT` / `LOGIN_USER_FAIL_WINDOW`）、
fail-open 降级，以及 `api_login` 的接线顺序（401 计数、400 不计数、成功清零）。

**自包含**：不依赖 `conftest.py` 的 DB fixture。Redis 用假实现 monkeypatch
`fastapi_app.core.redis_wrapper.get_client` —— 端点里是函数内局部 import
（`from fastapi_app.core.redis_wrapper import get_client`），所以 patch 目标必须是
**提供方模块** `redis_wrapper` 本身，而不是 `endpoints.auth`。
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, Request, Response

from fastapi_app.api.v1.endpoints import auth
from fastapi_app.core.exceptions import UnauthorizedError

AUTH_MOD = 'fastapi_app.api.v1.endpoints.auth'
REDIS_MOD = 'fastapi_app.core.redis_wrapper'


class _FakePipeline:
    """只实现被用到的那几条命令；`execute` 与真实 pipeline 一样**同批**返回结果列表。"""

    def __init__(self, redis: "_FakeRedis") -> None:
        self._redis = redis
        self._ops: list[tuple] = []

    def incr(self, key: str) -> "_FakePipeline":
        self._ops.append(('incr', key))
        return self

    def expire(self, key: str, ttl: int) -> "_FakePipeline":
        self._ops.append(('expire', key, ttl))
        return self

    async def execute(self) -> list:
        results = []
        for op in self._ops:
            name, *args = op
            results.append(await getattr(self._redis, name)(*args))
        return results


class _FakeRedis:
    """最小的异步 Redis 替身：get/incr/expire/delete/pipeline。"""

    def __init__(self, initial: dict | None = None) -> None:
        self.store: dict[str, int] = dict(initial or {})
        self.pipeline_calls = 0

    async def get(self, key: str):
        return self.store.get(key)

    async def incr(self, key: str) -> int:
        self.store[key] = int(self.store.get(key, 0)) + 1
        return self.store[key]

    async def expire(self, key: str, ttl: int) -> bool:
        return True

    async def delete(self, key: str) -> int:
        self.store.pop(key, None)
        return 1

    def pipeline(self) -> _FakePipeline:
        self.pipeline_calls += 1
        return _FakePipeline(self)


@pytest.fixture
def fake_redis() -> _FakeRedis:
    return _FakeRedis()


@pytest.fixture
def redis_patched(fake_redis: _FakeRedis):
    """把 `get_client()` 换成假 Redis（patch 目标是提供方模块，见模块 docstring）。"""
    with patch(f'{REDIS_MOD}.get_client', return_value=fake_redis):
        yield fake_redis


# ============================================================================
# 计数 / 锁定 / 清零
# ============================================================================
def test_user_fail_key_is_normalized() -> None:
    """同一账号的不同大小写/空格写法必须落到同一个键上（否则换个写法就重置了计数）。"""
    assert auth._user_fail_key('  Alice ') == 'login_user_fail:alice'
    assert auth._user_fail_key('ALICE') == auth._user_fail_key(' alice ')


async def test_failures_below_limit_do_not_lock(redis_patched: _FakeRedis) -> None:
    """未达上限时不得锁号（偶发打错几次不该被挡在门外）。"""
    for _ in range(auth.LOGIN_USER_FAIL_LIMIT - 1):
        await auth._record_login_failure('bob')

    await auth._check_user_lock('bob')  # 不抛

    assert redis_patched.store[auth._user_fail_key('bob')] == auth.LOGIN_USER_FAIL_LIMIT - 1


async def test_five_consecutive_failures_lock_account(redis_patched: _FakeRedis) -> None:
    """连续失败达 `LOGIN_USER_FAIL_LIMIT` 次后 `_check_user_lock` 抛 429（带 Retry-After）。"""
    for _ in range(auth.LOGIN_USER_FAIL_LIMIT):
        await auth._record_login_failure('bob')

    with pytest.raises(HTTPException) as exc_info:
        await auth._check_user_lock('bob')

    assert exc_info.value.status_code == 429
    assert '15分钟' in exc_info.value.detail
    assert exc_info.value.headers['Retry-After'] == str(auth.LOGIN_USER_FAIL_WINDOW)


async def test_record_failure_uses_single_pipeline_for_incr_and_expire(
    redis_patched: _FakeRedis,
) -> None:
    """incr 与 expire 必须同一 pipeline：否则「incr 成功、expire 失败」会留下永不过期的键。"""
    fails = await auth._record_login_failure('bob')

    assert fails == 1
    assert redis_patched.pipeline_calls == 1


async def test_reset_clears_failures(redis_patched: _FakeRedis) -> None:
    """成功登录后清零：清零后同一账号不再被锁。"""
    for _ in range(auth.LOGIN_USER_FAIL_LIMIT):
        await auth._record_login_failure('Carol')
    with pytest.raises(HTTPException):
        await auth._check_user_lock('Carol')

    await auth._reset_login_failures('Carol')

    assert auth._user_fail_key('Carol') not in redis_patched.store
    await auth._check_user_lock('Carol')  # 清零后放行


# ============================================================================
# Redis 不可用 → fail-open
# ============================================================================
async def test_check_user_lock_fails_open_when_client_is_none() -> None:
    """`get_client()` 返回 None（Redis 不可用）时放行，不能把全站登录锁死。"""
    with patch(f'{REDIS_MOD}.get_client', return_value=None):
        await auth._check_user_lock('dave')


async def test_check_user_lock_fails_open_when_redis_raises() -> None:
    """Redis 连接抛错时同样放行（fail-open），且计数/清零不抛。"""
    with patch(f'{REDIS_MOD}.get_client', side_effect=ConnectionError('no redis')):
        await auth._check_user_lock('dave')
        assert await auth._record_login_failure('dave') is None
        await auth._reset_login_failures('dave')


async def test_record_failure_is_silent_when_redis_unavailable() -> None:
    """Redis 不可用时 `_record_login_failure` 静默返回 None（不得改变登录响应）。"""
    with patch(f'{REDIS_MOD}.get_client', return_value=None):
        assert await auth._record_login_failure('dave') is None


# ============================================================================
# api_login 接线：401 计数 / 400 不计数 / 成功清零
# ============================================================================
def _login_request(ip: str = '10.0.0.9') -> Request:
    request = MagicMock(spec=Request)
    request.client = SimpleNamespace(host=ip)
    request.url.scheme = 'http'
    request.headers = {}
    return request


async def _call_api_login(authenticate: AsyncMock) -> auth.LoginResponse:
    """直接调用未限流的内层函数（slowapi 用 functools.wraps 包装，`__wrapped__` 可取）。"""
    data = auth.LoginRequest(username='  Dave ', password='whatever', remember=False)
    with patch.object(auth, '_check_login_rate_limit', new=AsyncMock()), \
         patch.object(auth, '_set_login_cookies'), \
         patch('fastapi_app.services.auth_service.authenticate_login', new=authenticate):
        return await auth.api_login.__wrapped__(
            request=_login_request(),
            response=MagicMock(spec=Response),
            data=data,
            db=AsyncMock(),
        )


async def test_api_login_counts_401_failure(redis_patched: _FakeRedis) -> None:
    """凭据错误（401）必须计数，并把原异常原样抛出（响应体/状态码不变）。"""
    authenticate = AsyncMock(side_effect=UnauthorizedError())

    with pytest.raises(UnauthorizedError):
        await _call_api_login(authenticate)

    assert redis_patched.store[auth._user_fail_key('Dave')] == 1


async def test_api_login_does_not_count_400_failure(redis_patched: _FakeRedis) -> None:
    """400（参数类错误）不计数：否则可被用来刷爆正常账号的失败额度。"""
    authenticate = AsyncMock(side_effect=HTTPException(status_code=400, detail='bad request'))

    with pytest.raises(HTTPException) as exc_info:
        await _call_api_login(authenticate)

    assert exc_info.value.status_code == 400
    assert auth._user_fail_key('Dave') not in redis_patched.store


async def test_api_login_resets_failures_on_success(redis_patched: _FakeRedis) -> None:
    """登录成功必须清零账户级计数（否则偶发打错会累积到锁号）。"""
    for _ in range(auth.LOGIN_USER_FAIL_LIMIT - 1):
        await auth._record_login_failure('Dave')

    authenticate = AsyncMock(return_value={
        'user': SimpleNamespace(id=7, username='Dave', is_super=False, factory=None, permissions=[]),
        'access_token': 'access-token',
        'refresh_token': 'refresh-token',
        'token_max_age': 3600,
        'refresh_max_age': 86400,
    })

    result = await _call_api_login(authenticate)

    assert result.success is True
    assert auth._user_fail_key('Dave') not in redis_patched.store
    # 成功响应体与既有契约一致（未因本次改动变形）
    assert result.access_token == 'access-token'
    assert result.user.user_id == 7


async def test_api_login_blocked_before_authenticate_when_locked(redis_patched: _FakeRedis) -> None:
    """已达上限时在校验凭据**之前**就 429：不再走口令哈希（省算力也避免继续喷洒）。"""
    for _ in range(auth.LOGIN_USER_FAIL_LIMIT):
        await auth._record_login_failure('Dave')
    authenticate = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await _call_api_login(authenticate)

    assert exc_info.value.status_code == 429
    authenticate.assert_not_awaited()
