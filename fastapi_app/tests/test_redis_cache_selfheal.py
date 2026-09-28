"""Redis 客户端自愈：init 失败后不得**永久**降级。

背景（2026-09-28 上线前审计）
----------------------------
`redis_cache.init_app()` 在 `ping()` 失败时把 `redis_client` 置 `None`，且
**此后永不重试**。于是「Redis 启动即不可用」（服务启动顺序、Redis 未就绪）
会让**整个进程生命周期**都只用内存降级 —— 缓存、撤销黑名单、限流全部受影响。

更糟的是这条与鉴权耦合：一旦敏感路由启用 fail-closed 的撤销校验，
`get_client()` 恒返回 `None` ⇒ 本地 LRU 未命中 ⇒ **永久 401**，
连合法 token 也拒，只能重启进程回正。

自愈设计的要点
--------------
`redis.asyncio.Redis` 的连接池**自带重连**：只要能拿到一个客户端对象，
Redis 恢复后命令就会自动成功。所以"永久降级"的根因只是
**客户端对象被丢成 None 后再也没重建**。

因此只需惰性重建客户端对象（`from_url`/`Redis(...)` 都是**惰性**的、不建连），
连通性交给首条命令去验证。为免在 Redis 长时间不可用时每次请求都重建连接池，
加一个指数退避窗口。
"""
from __future__ import annotations

import time

import pytest
import redis
from fastapi import HTTPException

from utils.redis_cache import RedisCacheManager


class _FakeClient:
    """可控的假客户端：ping 按需失败，其余命令不关心（本文件不测命令语义）。"""

    def __init__(self, *, ping_ok: bool = True):
        self.ping_ok = ping_ok
        self.closed = False

    async def ping(self):
        if not self.ping_ok:
            raise ConnectionError('redis down')
        return True

    async def aclose(self):
        self.closed = True


def _patch_from_url(monkeypatch: pytest.MonkeyPatch, client: _FakeClient) -> None:
    monkeypatch.setattr('utils.redis_cache.aioredis.from_url', lambda *a, **k: client)


async def test_init_failure_leaves_no_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """前置事实：init 失败时客户端为 None（自愈要解决的正是这个状态）。"""
    mgr = RedisCacheManager()
    _patch_from_url(monkeypatch, _FakeClient(ping_ok=False))

    await mgr.init_app(redis_url='redis://example:6379/0')

    assert mgr.redis_client is None


async def test_ensure_client_rebuilds_after_failed_init(monkeypatch: pytest.MonkeyPatch) -> None:
    """核心：init 失败过的 manager 仍能惰性重建客户端（不再是永久降级）。"""
    mgr = RedisCacheManager()
    _patch_from_url(monkeypatch, _FakeClient(ping_ok=False))
    await mgr.init_app(redis_url='redis://example:6379/0')
    assert mgr.redis_client is None

    rebuilt = _FakeClient()
    _patch_from_url(monkeypatch, rebuilt)

    assert mgr.ensure_client() is rebuilt


async def test_ensure_client_without_init_returns_none() -> None:
    """从未 init 过（没有连接参数）时不得凭空造客户端。"""
    mgr = RedisCacheManager()

    assert mgr.ensure_client() is None


async def test_ensure_client_returns_existing_without_rebuilding(monkeypatch: pytest.MonkeyPatch) -> None:
    """已连接时直接返回原对象，且**不得**再次构造客户端。

    仅断言身份不够：`_patch_from_url` 恒返回同一对象，即使"每次调用都重建"也成立。
    因此这里数 `from_url` 的调用次数。
    """
    mgr = RedisCacheManager()
    existing = _FakeClient()
    built: list[int] = []

    def counting_from_url(*args, **kwargs):
        built.append(1)
        return existing

    monkeypatch.setattr('utils.redis_cache.aioredis.from_url', counting_from_url)
    await mgr.init_app(redis_url='redis://example:6379/0')
    calls_after_init = len(built)

    assert mgr.ensure_client() is existing
    assert mgr.ensure_client() is existing
    assert len(built) == calls_after_init, 'ensure_client() 不应重复构造客户端'


async def test_ensure_client_respects_backoff_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """重建过一次后，退避窗口内不得再次重建（避免每请求重建连接池）。"""
    mgr = RedisCacheManager()
    _patch_from_url(monkeypatch, _FakeClient(ping_ok=False))
    await mgr.init_app(redis_url='redis://example:6379/0')

    _patch_from_url(monkeypatch, _FakeClient())

    assert mgr.ensure_client() is not None   # 第 1 次重建
    mgr.redis_client = None                  # 模拟重建出来的客户端又不可用被丢弃
    assert mgr.ensure_client() is None       # 窗口内不再重建


async def test_backoff_grows_and_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    """退避应指数增长且有上限，不能无限增长（否则 Redis 恢复后要等很久）。"""
    mgr = RedisCacheManager()
    _patch_from_url(monkeypatch, _FakeClient(ping_ok=False))
    await mgr.init_app(redis_url='redis://example:6379/0')

    delays: list[float] = []
    for _ in range(20):
        mgr.redis_client = None
        mgr._next_retry_at = 0.0            # 强制进入重建分支
        mgr.ensure_client()
        delays.append(mgr._retry_delay)

    assert delays[0] < delays[-1], '退避应增长'
    assert max(delays) <= RedisCacheManager.RETRY_MAX_DELAY, '退避必须有上限'


async def test_successful_init_resets_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """init 成功后应把退避复位，避免上次故障的残余延迟影响后续重建。"""
    mgr = RedisCacheManager()
    _patch_from_url(monkeypatch, _FakeClient(ping_ok=False))
    await mgr.init_app(redis_url='redis://example:6379/0')
    for _ in range(5):
        mgr.redis_client = None
        mgr._next_retry_at = 0.0
        _patch_from_url(monkeypatch, _FakeClient())
        mgr.ensure_client()
    assert mgr._retry_delay > RedisCacheManager.RETRY_INITIAL_DELAY

    _patch_from_url(monkeypatch, _FakeClient())
    await mgr.init_app(redis_url='redis://example:6379/0')

    assert mgr._retry_delay == RedisCacheManager.RETRY_INITIAL_DELAY
    assert mgr._next_retry_at == 0.0


def test_get_client_uses_selfheal(monkeypatch: pytest.MonkeyPatch) -> None:
    """`redis_wrapper.get_client()` 必须走自愈 —— 它是撤销黑名单/限流等裸客户端路径的入口。"""
    from fastapi_app.core import redis_wrapper
    from utils.redis_cache import redis_cache

    rebuilt = _FakeClient()
    monkeypatch.setattr(redis_cache, 'redis_client', None)
    monkeypatch.setattr(redis_cache, '_connect_kwargs', {'url': 'redis://example:6379/0'})
    monkeypatch.setattr(redis_cache, '_next_retry_at', 0.0)
    monkeypatch.setattr(redis_cache, '_retry_delay', RedisCacheManager.RETRY_INITIAL_DELAY)
    _patch_from_url(monkeypatch, rebuilt)

    assert redis_wrapper.get_client() is rebuilt


async def test_cache_get_uses_selfheal(monkeypatch: pytest.MonkeyPatch) -> None:
    """缓存读路径同样要自愈（否则 Redis 恢复后缓存仍一直走内存降级）。

    ⚠️ 刻意**不**预先调用 `ensure_client()`：那样会把客户端先建好，于是断言对
    「旧的 `if self.redis_client:` 短路实现」也成立 —— 测试会变成空转。
    改为断言假客户端真的收到了命令，这才区分得开两种实现。
    """
    mgr = RedisCacheManager()
    _patch_from_url(monkeypatch, _FakeClient(ping_ok=False))
    await mgr.init_app(redis_url='redis://example:6379/0')
    assert mgr.redis_client is None

    seen: list[str] = []

    class _Readable(_FakeClient):
        async def get(self, key):
            seen.append(key)
            return None

    _patch_from_url(monkeypatch, _Readable())

    assert await mgr.get('some-key') is None
    assert seen == ['erp:some-key'], 'get() 未走到 Redis 分支（说明仍是旧的短路行为）'
    assert mgr.redis_client is not None


async def test_connection_failure_demotes_and_backs_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """命令遇连接类失败 → 降级 + 进入退避。

    这恢复被惰性重建破坏的短路行为：Redis 持续不可用期间，旧实现是
    `redis_client is None` 直接走内存（零 I/O、零日志），而"只重建不降级"
    会让**每个**请求都去连一次并各打一条 warning。
    """
    mgr = RedisCacheManager()
    _patch_from_url(monkeypatch, _FakeClient(ping_ok=False))
    await mgr.init_app(redis_url='redis://example:6379/0')

    attempts: list[str] = []

    class _Refusing(_FakeClient):
        async def get(self, key):
            attempts.append(key)
            raise redis.exceptions.ConnectionError('refused')

    _patch_from_url(monkeypatch, _Refusing())

    await mgr.get('k1')
    assert mgr.redis_client is None, '连接类失败应降级'
    assert mgr._next_retry_at > time.monotonic(), '应进入未来的退避窗口'

    # 退避窗口内：不得再尝试连接（零 I/O），直接走内存降级
    assert mgr.ensure_client() is None
    assert await mgr.get('k2') is None
    assert attempts == ['erp:k1'], f'退避窗口内不应再连 Redis，实际 {attempts}'


async def test_non_connection_error_does_not_demote(monkeypatch: pytest.MonkeyPatch) -> None:
    """协议类错误（如 WRONGTYPE）不是连通性问题，**不得**把客户端丢掉。"""
    mgr = RedisCacheManager()
    _patch_from_url(monkeypatch, _FakeClient(ping_ok=False))
    await mgr.init_app(redis_url='redis://example:6379/0')

    class _ProtocolError(_FakeClient):
        async def get(self, key):
            raise redis.exceptions.ResponseError('WRONGTYPE')

    _patch_from_url(monkeypatch, _ProtocolError())

    client = mgr.ensure_client()
    await mgr.get('k')

    assert mgr.redis_client is client, '非连接类错误不应触发降级'


async def test_close_prevents_later_rebuild(monkeypatch: pytest.MonkeyPatch) -> None:
    """close() 之后不得再惰性重建（否则关停后迟到的请求会造出永不关闭的连接池）。"""
    mgr = RedisCacheManager()
    _patch_from_url(monkeypatch, _FakeClient(ping_ok=False))
    await mgr.init_app(redis_url='redis://example:6379/0')

    await mgr.close()

    rebuilt = _FakeClient()
    _patch_from_url(monkeypatch, rebuilt)
    assert mgr.ensure_client() is None


async def test_recovers_after_outage(monkeypatch: pytest.MonkeyPatch) -> None:
    """整条自愈环路：故障 → 降级 → 窗口过期 → 重建并**真正使用**客户端。"""
    mgr = RedisCacheManager()
    _patch_from_url(monkeypatch, _FakeClient(ping_ok=False))
    await mgr.init_app(redis_url='redis://example:6379/0')

    class _Refusing(_FakeClient):
        async def get(self, key):
            raise redis.exceptions.ConnectionError('refused')

    _patch_from_url(monkeypatch, _Refusing())
    await mgr.get('k1')
    assert mgr.redis_client is None, '故障后应降级'

    seen: list[str] = []

    class _Readable(_FakeClient):
        async def get(self, key):
            seen.append(key)
            return None

    _patch_from_url(monkeypatch, _Readable())
    mgr._next_retry_at = 0.0            # 让退避窗口过期（不 sleep）

    assert await mgr.get('k2') is None
    assert seen == ['erp:k2'], '恢复后应重新使用 Redis 而非一直内存降级'
    assert mgr.redis_client is not None


async def test_successful_command_resets_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """命令成功后必须复位退避。

    若只在 init 时复位：一次长时间故障会把退避顶到上限（60s），Redis 恢复后
    退避仍停在 60s —— 于是**之后一次偶发抖动**就要等 60s 才再尝试。
    对 fail-closed 路由（/backup）这段时间就是**合法用户的 60s 401**。
    """
    mgr = RedisCacheManager()
    _patch_from_url(monkeypatch, _FakeClient(ping_ok=False))
    await mgr.init_app(redis_url='redis://example:6379/0')

    class _Refusing(_FakeClient):
        async def get(self, key):
            raise redis.exceptions.ConnectionError('refused')

    _patch_from_url(monkeypatch, _Refusing())
    for _ in range(20):
        mgr.redis_client = None
        mgr._next_retry_at = 0.0
        await mgr.get('k')
    assert mgr._retry_delay == RedisCacheManager.RETRY_MAX_DELAY, '退避应已顶到上限'

    class _Readable(_FakeClient):
        async def get(self, key):
            return None

    _patch_from_url(monkeypatch, _Readable())
    mgr.redis_client = None
    mgr._next_retry_at = 0.0
    await mgr.get('k')

    assert mgr._retry_delay == RedisCacheManager.RETRY_INITIAL_DELAY, '命令成功后应复位退避'
    assert mgr._next_retry_at == 0.0


async def test_blacklist_path_reports_failure_to_cache_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    """撤销黑名单（裸客户端 + fail-closed）必须把失败告知缓存管理器。

    裸客户端路径不经过 `RedisCacheManager` 的包装方法，若不告知就**不进入**
    降级/退避：Redis 持续不可用时每个请求都会真连一次并各打一条日志 ——
    这正是 fail-closed 路由（/backup）在故障期间的路径。
    """
    from fastapi_app.core.auth import blacklist
    from utils.redis_cache import redis_cache

    class _Refusing(_FakeClient):
        async def exists(self, key):
            raise redis.ConnectionError('refused')

    monkeypatch.setattr('fastapi_app.core.redis_wrapper.get_client', lambda: _Refusing())
    reported: list[Exception] = []
    monkeypatch.setattr(redis_cache, 'note_command_failure', lambda exc: reported.append(exc))

    # fail_closed=True 且本地 LRU 未命中 → 必须 401
    with pytest.raises(HTTPException):
        await blacklist.is_token_revoked('some-unknown-jti', fail_closed=True)

    assert reported, '撤销黑名单失败时未告知缓存管理器（该路径不会降级/退避）'


async def test_blacklist_success_also_reports_to_cache_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    """成功的裸命令同样要告知（复位退避）。

    只报失败不报成功的话：一次故障把退避窗口挂上后，即使 Redis 已经好了，
    窗口也不会被清掉 —— 之后一次抖动仍要等满额时间。上一条测试只覆盖了失败侧。
    """
    from fastapi_app.core.auth import blacklist
    from utils.redis_cache import redis_cache

    class _Ok(_FakeClient):
        async def exists(self, key):
            return 0

    monkeypatch.setattr('fastapi_app.core.redis_wrapper.get_client', lambda: _Ok())
    noted: list[int] = []
    monkeypatch.setattr(redis_cache, 'note_command_success', lambda: noted.append(1))

    assert await blacklist.is_token_revoked('jti-not-revoked') is False
    assert noted, '成功的 exists 未告知缓存管理器（退避不会被复位）'


async def test_fallback_cache_honours_per_call_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """降级缓存必须按**每次调用的 timeout** 过期，而不是一律用 default_timeout。

    此前 set() 只记写入时刻、读取时统一比 default_timeout（默认 300s），于是
    `safe_set(key, timeout=30)` 在 Redis 不可用时实际活 300 秒 —— refresh 轮换的
    30 秒 grace 窗口会悄悄变成 300 秒（安全复审 2026-09-28 指出的真实缺陷）。
    """
    mgr = RedisCacheManager()
    _patch_from_url(monkeypatch, _FakeClient(ping_ok=False))
    await mgr.init_app(redis_url='redis://example:6379/0')
    assert mgr.default_timeout == 300, '前提：默认 TTL 远大于本次调用的 TTL'

    await mgr.set('k', 'v', timeout=30)
    assert await mgr.get('k') == 'v'

    # 把该条过期时刻拨到"现在"之前，模拟 30 秒已过（default_timeout 还剩很多）
    mgr._fallback_timestamps[mgr._make_key('k')] = time.time() - 1
    assert await mgr.get('k') is None, '降级缓存未按 per-call timeout 过期'
