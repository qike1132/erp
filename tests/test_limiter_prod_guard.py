"""L3：生产限流缺 Redis 时必须启动失败，避免 8 worker 各自计数放大阈值。"""
import pytest


def test_production_without_redis_fails(monkeypatch):
    from fastapi_app.core import limiter

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("REDIS_CACHE_URL", raising=False)
    with pytest.raises(RuntimeError, match="REDIS_CACHE_URL"):
        limiter.assert_production_limiter_storage()


def test_development_falls_back(monkeypatch):
    from fastapi_app.core import limiter

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("REDIS_CACHE_URL", raising=False)
    limiter.assert_production_limiter_storage()  # 不抛
