"""
cache.py 单元测试

覆盖：L1 本地缓存命中/过期/失效、cache_result 装饰器、_match_pattern
"""
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from fastapi_app.core.cache import (
    _cache_local,
    _match_pattern,
    cache_result,
    invalidate_cache,
    invalidate_local_cache,
)


@pytest.fixture(autouse=True)
def clear_local_cache():
    """每个测试前后清空 L1 缓存"""
    _cache_local.clear()
    yield
    _cache_local.clear()


# ============================================================
# _match_pattern
# ============================================================

class TestMatchPattern:
    def test_exact_match(self):
        assert _match_pattern("orders:list:abc", "orders:list:abc")

    def test_wildcard(self):
        assert _match_pattern("orders:list:abc", "orders:*")

    def test_no_match(self):
        assert not _match_pattern("orders:list:abc", "products:*")


# ============================================================
# invalidate_local_cache
# ============================================================

class TestInvalidateLocalCache:
    def test_removes_matching_keys(self):
        _cache_local["orders:list:a"] = ("v1", datetime.now() + timedelta(seconds=60))
        _cache_local["orders:list:b"] = ("v2", datetime.now() + timedelta(seconds=60))
        _cache_local["products:x"] = ("v3", datetime.now() + timedelta(seconds=60))

        deleted = invalidate_local_cache("orders:*")
        assert deleted == 2
        assert "products:x" in _cache_local

    def test_no_match_returns_zero(self):
        _cache_local["a:b"] = ("v", datetime.now() + timedelta(seconds=60))
        assert invalidate_local_cache("z:*") == 0


# ============================================================
# cache_result 装饰器
# ============================================================

class TestCacheResultDecorator:
    @pytest.mark.asyncio
    async def test_caches_result_in_l1(self):
        call_count = 0

        @cache_result(key_prefix="test_fn", ttl=60, local_ttl=30)
        async def my_fn(x):
            nonlocal call_count
            call_count += 1
            return {"value": x}

        with patch("fastapi_app.core.cache._get_redis_cache", return_value=None):
            r1 = await my_fn(42)
            r2 = await my_fn(42)

        assert r1 == {"value": 42}
        assert r2 == {"value": 42}
        assert call_count == 1  # second call served from L1

    @pytest.mark.asyncio
    async def test_expired_l1_refetches(self):
        call_count = 0

        @cache_result(key_prefix="test_exp", ttl=60, local_ttl=1)
        async def my_fn():
            nonlocal call_count
            call_count += 1
            return "result"

        with patch("fastapi_app.core.cache._get_redis_cache", return_value=None):
            await my_fn()
            # Manually expire the L1 cache entry
            for key in list(_cache_local.keys()):
                if key.startswith("test_exp:"):
                    _cache_local[key] = (_cache_local[key][0], datetime.now() - timedelta(seconds=1))
            await my_fn()

        assert call_count == 2

    @pytest.mark.asyncio
    async def test_custom_key_builder(self):
        @cache_result(key_prefix="kb", key_builder=lambda x: f"item_{x}")
        async def my_fn(x):
            return x * 2

        with patch("fastapi_app.core.cache._get_redis_cache", return_value=None):
            result = await my_fn(5)

        assert result == 10
        assert "kb:item_5" in _cache_local

    @pytest.mark.asyncio
    async def test_fallback_on_decorator_error(self):
        """装饰器内部异常时降级到直接调用"""
        @cache_result(key_prefix="err", key_builder=lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        async def my_fn():
            return "fallback_value"

        with patch("fastapi_app.core.cache._get_redis_cache", return_value=None):
            result = await my_fn()

        assert result == "fallback_value"


# ============================================================
# invalidate_cache (async, with Redis mock)
# ============================================================

class TestInvalidateCache:
    @pytest.mark.asyncio
    async def test_clears_l1_and_redis(self):
        _cache_local["orders:a"] = ("v", datetime.now() + timedelta(seconds=60))

        mock_redis = AsyncMock()
        mock_redis.keys = AsyncMock(return_value=["orders:a", "orders:b"])
        mock_redis.delete = AsyncMock(return_value=2)

        with patch("fastapi_app.core.cache._get_redis_cache", return_value=mock_redis):
            deleted = await invalidate_cache("orders:*")

        assert "orders:a" not in _cache_local
        assert deleted == 3  # 1 local + 2 redis

    @pytest.mark.asyncio
    async def test_works_without_redis(self):
        _cache_local["x:1"] = ("v", datetime.now() + timedelta(seconds=60))

        with patch("fastapi_app.core.cache._get_redis_cache", return_value=None):
            deleted = await invalidate_cache("x:*")

        assert deleted == 1
