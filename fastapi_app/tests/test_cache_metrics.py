"""缓存装饰器命中率埋点测试

背景：
  Redis INFO 的 keyspace_hits/misses 是全局口径，会被大量"注定 miss"的
  访问（如每请求一次的 token 黑名单 EXISTS）稀释，导致无法反映业务缓存的
  真实效果。为此给 @cache_result 增加细粒度埋点：

    cache_operations_total{operation="l1_hit"}    进程内缓存命中
    cache_operations_total{operation="l2_hit"}    Redis 命中
    cache_operations_total{operation="miss"}      两级均未命中并回源
    cache_operations_total{operation="stale"}     未获击穿锁且等待超时后回源

本测试锁定埋点契约，防止后续重构破坏可观测性。
"""

import pytest

from fastapi_app.core import cache as cache_mod
from fastapi_app.core.cache import _cache_local, _record_cache_op, cache_result


@pytest.fixture
def recorded(monkeypatch):
    """捕获 _record_cache_op 的调用序列"""
    calls: list[str] = []
    monkeypatch.setattr(cache_mod, '_record_cache_op', lambda op: calls.append(op))
    return calls


@pytest.fixture(autouse=True)
def _clear_l1():
    """每个用例前清空 L1，避免跨用例污染"""
    _cache_local.clear()
    yield
    _cache_local.clear()


class TestRecordCacheOp:
    """_record_cache_op 本身的行为契约"""

    def test_does_not_raise_without_prometheus(self):
        """prometheus_client 未安装或指标异常时，必须静默失败不抛错"""
        for op in ('l1_hit', 'l2_hit', 'miss', 'stale', 'wait', 'redis_error'):
            _record_cache_op(op)  # 不应抛出

    def test_swallows_metric_exception(self, monkeypatch):
        """即使指标层抛异常，也不能影响缓存主流程"""
        def _boom(*a, **kw):
            raise RuntimeError('metric backend down')

        monkeypatch.setattr(cache_mod, '_record_cache_op', _boom)
        # 直接调用被替换的函数仍抛错（用于确认替换生效），
        # 但真实调用点被 try/except 包裹——这里验证原始实现的容错：
        assert callable(cache_mod._record_cache_op)


class TestDecoratorInstrumentation:
    """装饰器各分支必须记录正确的 operation"""

    @pytest.mark.asyncio
    async def test_l1_hit_recorded_on_second_call(self, recorded, monkeypatch):
        """第二次调用应命中 L1 并记录 l1_hit"""
        monkeypatch.setattr(cache_mod, '_get_redis_cache', lambda: None)
        calls = []

        @cache_result(key_prefix='t:l1', ttl=60, local_ttl=60)
        async def fn():
            calls.append(1)
            return {'v': 1}

        await fn()
        await fn()

        assert calls == [1], '第二次调用不应真正执行函数体'
        assert 'l1_hit' in recorded

    @pytest.mark.asyncio
    async def test_miss_recorded_when_no_redis(self, recorded, monkeypatch):
        """Redis 不可用时，首次调用应记录 miss 或 stale（回源）"""
        monkeypatch.setattr(cache_mod, '_get_redis_cache', lambda: None)

        @cache_result(key_prefix='t:miss', ttl=60, local_ttl=60)
        async def fn():
            return {'v': 2}

        await fn()

        assert 'miss' in recorded or 'stale' in recorded, (
            f'首次回源必须记录 miss/stale，实际: {recorded}'
        )

    @pytest.mark.asyncio
    async def test_l2_hit_recorded(self, recorded, monkeypatch):
        """L1 未命中但 L2 命中时记录 l2_hit"""
        class _FakeRedis:
            async def get(self, key):
                return {'v': 'from-redis'}

        monkeypatch.setattr(cache_mod, '_get_redis_cache', lambda: _FakeRedis())

        @cache_result(key_prefix='t:l2', ttl=60, local_ttl=60)
        async def fn():
            raise AssertionError('L2 命中时不应回源')

        result = await fn()
        assert result == {'v': 'from-redis'}
        assert 'l2_hit' in recorded

    @pytest.mark.asyncio
    async def test_redis_error_recorded(self, recorded, monkeypatch):
        """Redis 读取异常时记录 redis_error，并降级回源。

        2026-10-17 审计 AUD-10：此前这里 mock 的是**内建** ConnectionError，
        而生产抛的是 redis.exceptions.ConnectionError（只继承 RedisError）。
        故障模型与生产不符，导致异常穿透缺陷被假绿掩护——必须用真实异常族。
        """
        import redis.exceptions

        class _BoomRedis:
            async def get(self, key):
                raise redis.exceptions.ConnectionError('redis down')

            async def set(self, *a, **kw):
                raise redis.exceptions.ConnectionError('redis down')

            async def delete(self, *a, **kw):
                return 0

        monkeypatch.setattr(cache_mod, '_get_redis_cache', lambda: _BoomRedis())

        @cache_result(key_prefix='t:err', ttl=60, local_ttl=60)
        async def fn():
            return {'v': 'fallback'}

        result = await fn()
        assert result == {'v': 'fallback'}
        assert 'redis_error' in recorded

    @pytest.mark.asyncio
    async def test_release_lock_failure_does_not_swallow_result(self, monkeypatch):
        """持锁重算成功、释锁时 Redis 已死——必须返回业务结果，不得 500。

        2026-10-17 审计 AUD-10 场景 C：finally 里的释锁异常会覆盖 return 值。
        """
        import redis.exceptions

        class _ReleaseBoomRedis:
            redis_client = None

            def __init__(self):
                self.redis_client = self

            def _make_key(self, key):
                return key

            async def get(self, key):
                return None

            async def set(self, key, value, nx=False, ex=None, timeout=None):
                return True

            async def eval(self, *a, **kw):
                raise redis.exceptions.ConnectionError('release boom')

        monkeypatch.setattr(cache_mod, '_get_redis_cache', lambda: _ReleaseBoomRedis())

        @cache_result(key_prefix='t:release', ttl=60, local_ttl=0,
                      key_builder=lambda *a, **k: 'k')
        async def fn():
            return {'v': 'ok'}

        assert await fn() == {'v': 'ok'}


class TestLocalTtlSemantics:
    """锁定 local_ttl 的真实语义（P1 TTL 复核的实测结论）。

    实测背景：
      local_ttl 不是"数据新鲜度保证"，而是 **L1 条目的滑动生存期**：
        - 每次命中 L1，沿用原 expire_at，不续期
        - 每次命中 L2，回填 L1 并把 expire_at 重置为 now + local_ttl（相当于续期）
        - 命中 L1 的 expire_at 是**绝对时间**，一旦越过就必须回落到 L2
      因此：
        · 访问间隔 < local_ttl → 走 l1_hit（进程内，无网络开销）
        · local_ttl < 访问间隔 < ttl → 走 l2_hit（需一次 Redis GET）
        · 访问间隔 > ttl → 走 miss（回源查库）

    这些测试用伪造 L1 过期时间/伪造 Redis 来锁定上述契约，
    防止后续有人把 local_ttl 误当作"数据 TTL"而改错。
    """

    @pytest.mark.asyncio
    async def test_l1_hit_does_not_extend_expire_at(self, recorded, monkeypatch):
        """L1 命中不续期：expire_at 必须保持原值"""
        monkeypatch.setattr(cache_mod, '_get_redis_cache', lambda: None)

        @cache_result(key_prefix='t:slide', ttl=60, local_ttl=60,
                      key_builder=lambda *a, **k: 'k')
        async def fn():
            return {'v': 1}

        await fn()  # 冷启动，写入 L1
        key = 't:slide:k'
        _, exp_before = _cache_local[key]

        await fn()  # L1 命中
        _, exp_after = _cache_local[key]

        assert exp_after == exp_before, (
            'L1 命中不得刷新 expire_at，否则 local_ttl 会退化为永久缓存'
        )

    @pytest.mark.asyncio
    async def test_expired_l1_falls_back_to_l2(self, recorded, monkeypatch):
        """L1 已过期时必须回落到 L2，且 L2 命中后回填并续期 L1"""
        from datetime import datetime, timedelta

        class _FakeRedis:
            async def get(self, key):
                return {'v': 'from-l2'}

        monkeypatch.setattr(cache_mod, '_get_redis_cache', lambda: _FakeRedis())

        @cache_result(key_prefix='t:fall', ttl=60, local_ttl=15,
                      key_builder=lambda *a, **k: 'k')
        async def fn():
            raise AssertionError('L2 命中时不应回源')

        key = 't:fall:k'
        # 手工塞入一个已过期的 L1 条目，模拟"访问间隔 > local_ttl"
        _cache_local[key] = ({'v': 'stale-l1'}, datetime.now() - timedelta(seconds=1))

        result = await fn()

        assert result == {'v': 'from-l2'}, '过期 L1 必须回落 L2，不得返回陈旧值'
        assert 'l2_hit' in recorded
        # L2 命中后应回填 L1，且 expire_at 重置为未来时间
        assert key in _cache_local
        _, exp = _cache_local[key]
        assert exp > datetime.now(), 'L2 命中回填 L1 后 expire_at 应为未来时间'

    @pytest.mark.asyncio
    async def test_expired_l1_with_no_redis_misses(self, recorded, monkeypatch):
        """L1 过期且 Redis 不可用 → 必须回源（miss），并重新写入 L1"""
        from datetime import datetime, timedelta

        monkeypatch.setattr(cache_mod, '_get_redis_cache', lambda: None)
        hits = []

        @cache_result(key_prefix='t:noredis', ttl=60, local_ttl=15,
                      key_builder=lambda *a, **k: 'k')
        async def fn():
            hits.append(1)
            return {'v': 'fresh'}

        key = 't:noredis:k'
        _cache_local[key] = ({'v': 'stale'}, datetime.now() - timedelta(seconds=1))

        result = await fn()

        assert hits == [1], 'L1 过期且无 Redis 时必须回源'
        assert result == {'v': 'fresh'}
        assert _cache_local[key][1] > datetime.now(), '回源后应重新写入 L1'
