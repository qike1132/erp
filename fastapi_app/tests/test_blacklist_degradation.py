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
