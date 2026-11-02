"""logout 不得豁免 CSRF。

`/auth/logout` 无鉴权依赖（允许匿名清理过期会话），却同时被列入 CSRF 豁免：
跨站表单 POST 就能让受害者被强制登出，且响应会删掉本地 cookie。
前端所有非 GET 请求都经 request.ts 自动带 X-CSRF-Token，移除豁免不会打断登出。
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from fastapi_app.main import app


@pytest.mark.asyncio
async def test_logout_without_csrf_token_is_rejected() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        resp = await client.post('/api/v1/auth/logout')
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_logout_with_double_submit_token_passes() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        await client.get('/api/v1/auth/me')  # 中间件顺手下发 fastapi_csrf_token
        token = client.cookies.get('fastapi_csrf_token')
        assert token, '未下发 CSRF cookie'
        resp = await client.post(
            '/api/v1/auth/logout', headers={'X-CSRF-Token': token},
        )
    assert resp.status_code != 403
