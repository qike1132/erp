"""H4：fail-open 降级必须可观测（原 record_degradation 无任何生产调用点）。"""
import pytest

from fastapi_app.core import middleware


@pytest.fixture(autouse=True)
def _isolate_degradation_state():
    middleware.clear_degradations()
    yield
    middleware.clear_degradations()


@pytest.mark.asyncio
async def test_fail_open_records_degradation(monkeypatch):
    # blacklist 在函数内 from redis_wrapper import get_client，故补丁打在源模块上
    monkeypatch.setattr("fastapi_app.core.redis_wrapper.get_client", lambda: None)

    from fastapi_app.core.auth.blacklist import is_token_revoked

    assert await is_token_revoked("jti-1", fail_closed=False) is False
    assert "token_revocation_fail_open" in middleware.degraded_reasons()


@pytest.mark.asyncio
async def test_degraded_reasons_all_reads_single_key(monkeypatch):
    """跨 worker 汇总只读一个固定键，不得用 KEYS 扫全键空间。"""
    stored = {"value": ["remote_reason"]}

    async def _safe_get(key, fallback=None, context=""):
        return stored["value"]

    async def _safe_set(key, value, timeout=300, context=""):
        stored["value"] = value
        return True

    monkeypatch.setattr("fastapi_app.core.redis_wrapper.safe_get", _safe_get)
    monkeypatch.setattr("fastapi_app.core.redis_wrapper.safe_set", _safe_set)

    middleware.clear_degradations()
    assert "remote_reason" in await middleware.degraded_reasons_all()

    await middleware.publish_degradation("local_reason")
    assert "local_reason" in stored["value"]
    assert "local_reason" in await middleware.degraded_reasons_all()


@pytest.mark.asyncio
async def test_maintenance_probe_fail_open_records_degradation(monkeypatch):
    """维护模式探测异常且哨兵未激活 = fail-open 放行，必须登记降级。"""
    from fastapi_app.core import maintenance

    async def _boom():
        raise RuntimeError("redis down")

    monkeypatch.setattr(maintenance, "_get_client", _boom)
    monkeypatch.setattr(maintenance, "_sentinel_active", lambda: False)
    monkeypatch.setattr(maintenance, "_report_read_failure", lambda exc: None)

    middleware.clear_degradations()
    assert await maintenance.is_maintenance_mode() is False
    assert "maintenance_mode_probe_fail_open" in middleware.degraded_reasons()
