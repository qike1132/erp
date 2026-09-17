"""CSRF cookie 的 Secure 属性必须随请求实际 scheme 变化（回归：局域网 HTTP 下写请求全 403）。

根因（2026-09-17 真实浏览器实测）
--------------------------------
1. 生产模式下 CSRF 中间件固定给 `fastapi_csrf_token` 加 `Secure`（`CSRF_COOKIE_SECURE` 缺省即 true）；
2. 浏览器**只在可信来源**（https、localhost、127.0.0.1）接受 Secure cookie；局域网明文 HTTP
   （如 http://192.168.0.95:3000）上会**直接丢弃**该 cookie；
3. 前端 `src/api/request.ts` 的 `getCsrfFromCookie()` 因此读不到 token ⇒ 写请求不带
   `X-CSRF-Token` ⇒ 后端 403「CSRF token 验证失败」⇒ 该 origin 下**所有** POST/PUT/DELETE 全失败。
4. 登录 cookie 早已按 scheme 自适应（`api/v1/endpoints/auth.py::_set_login_cookies`），
   这正是「能登录、但写不了」的原因——CSRF cookie 当时漏了同一套判定。

实测对照（真实 Edge，非推断）
----------------------------
| origin                    | cookie jar               | 从 cookie 取 token 后 POST |
|---------------------------|--------------------------|----------------------------|
| http://127.0.0.1:3000     | 有 fastapi_csrf_token    | 401（CSRF 已放行）          |
| http://192.168.0.95:3000  | **空**                   | 403 CSRF token 验证失败     |
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from fastapi_app.core.config import settings
from fastapi_app.main import app

# TrustedHostMiddleware 只放行 ALLOWED_HOSTS 中的主机；这里用真实局域网 IP 复现现场
_PROBE_HOST = "192.168.0.95"
if _PROBE_HOST not in settings.ALLOWED_HOSTS:
    settings.ALLOWED_HOSTS.append(_PROBE_HOST)


def _csrf_set_cookie(response) -> str:
    """取响应里 fastapi_csrf_token 的 Set-Cookie 原文。"""
    for raw in response.headers.get_list("set-cookie"):
        if raw.startswith("fastapi_csrf_token="):
            return raw
    return ""


async def _csrf_cookie_header(base_url: str, headers: dict | None = None) -> str:
    """发一次探针请求，返回 CSRF cookie 的 Set-Cookie 原文。

    路径用不存在的 /api/v1/health 即可：中间件对所有响应都会下发该 cookie。
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url=base_url) as client:
        resp = await client.get("/api/v1/health", headers=headers or {})
    assert resp.status_code != 500, f"探针请求异常：{resp.status_code} {resp.text[:200]}"
    return _csrf_set_cookie(resp)


@pytest.mark.asyncio
async def test_csrf_cookie_secure_follows_request_scheme(monkeypatch) -> None:
    """明文 HTTP 不得带 Secure；反代声明 https 时仍应带 Secure。"""
    monkeypatch.setenv("APP_ENV", "production")
    # 防止「因为没进生产模式」而假绿：生产模式下 _csrf_secure 缺省为 true，本用例才有意义
    assert settings.is_production is True, "APP_ENV=production 未生效，本用例失去意义"

    # 1) 明文 HTTP（局域网 IP）⇒ 不得带 Secure，否则浏览器直接丢弃 → 写请求全 403
    http_cookie = await _csrf_cookie_header(f"http://{_PROBE_HOST}:3000")
    assert http_cookie, "未下发 fastapi_csrf_token cookie"
    assert "Secure" not in http_cookie, f"明文 HTTP 下不应带 Secure：{http_cookie}"

    # 2) 反向代理声明 https ⇒ 仍应带 Secure（不得因为本次修复而弱化 HTTPS 部署）
    https_cookie = await _csrf_cookie_header(
        f"http://{_PROBE_HOST}:3000", headers={"X-Forwarded-Proto": "https"}
    )
    assert "Secure" in https_cookie, f"HTTPS 下应带 Secure：{https_cookie}"
