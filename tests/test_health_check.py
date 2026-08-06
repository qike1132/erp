"""
健康检查测试 — FastAPI 异步版

验证 /api/health 和根路径端点可用。
"""
import pytest


@pytest.mark.asyncio
async def test_v1_health_check(async_client):
    """测试 /api/health 健康检查"""
    resp = await async_client.get("/api/health")
    assert resp.status_code in (200, 503)
    data = resp.json()
    assert data.get("status") is not None


@pytest.mark.asyncio
async def test_root_endpoint(async_client):
    """测试根路径"""
    resp = await async_client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert "version" in data
