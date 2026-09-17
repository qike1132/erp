"""GZip 中间件「压缩归属」修复的回归测试（D5）。

背景（2026-09-17）：`_setup_gzip` 此前按 `settings.is_production` 推断「生产环境
由 Nginx 统一压缩，跳过 GZipMiddleware」。当 nginx 缺席（本次实况）时，全站零
压缩——`/metrics` 未压缩体积数倍于 gzip 后。修复后默认始终开启 GZipMiddleware，
仅在显式设置 `APP_GZIP_DISABLED=true` 时才关闭（不再按环境名推断）。

本测试在进程内用 ASGI 直连验证响应头，不依赖任何运行中的服务。
"""
from __future__ import annotations

import httpx
from fastapi import FastAPI

from fastapi_app.core.middleware import _setup_gzip

_BIG_PAYLOAD = "x" * 5000


def _build_app() -> FastAPI:
    """构造一个带大响应体的最小 app，并套用被测 `_setup_gzip`。"""
    app = FastAPI()

    @app.get("/big")
    async def big() -> dict:
        return {"data": _BIG_PAYLOAD}

    _setup_gzip(app)
    return app


async def _probe(app: FastAPI) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        return await c.get("/big", headers={"Accept-Encoding": "gzip"})


async def test_gzip_enabled_by_default(monkeypatch):
    """默认（含生产环境）必须压缩：正文 >1000B + 客户端接受 gzip → content-encoding: gzip。"""
    monkeypatch.delenv("APP_GZIP_DISABLED", raising=False)
    resp = await _probe(_build_app())
    assert resp.status_code == 200
    assert resp.headers.get("content-encoding") == "gzip"
    assert resp.headers.get("vary") == "Accept-Encoding"


async def test_gzip_disabled_by_explicit_env(monkeypatch):
    """显式关闸（APP_GZIP_DISABLED=true）时应不压缩。"""
    monkeypatch.setenv("APP_GZIP_DISABLED", "true")
    resp = await _probe(_build_app())
    assert resp.status_code == 200
    assert resp.headers.get("content-encoding") is None
