"""E2E 目标后端身份端点：只在 APP_ENV=test 暴露，生产必须 404。"""
import pytest


@pytest.mark.asyncio
async def test_identity_returns_test_database(client, monkeypatch):
    monkeypatch.setenv('APP_ENV', 'test')
    resp = await client.get('/api/health/e2e-identity')
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data['app_env'] == 'test'
    assert isinstance(data['database'], str) and data['database']


@pytest.mark.asyncio
async def test_identity_is_hidden_outside_test(client, monkeypatch):
    monkeypatch.setenv('APP_ENV', 'production')
    resp = await client.get('/api/health/e2e-identity')
    assert resp.status_code == 404
