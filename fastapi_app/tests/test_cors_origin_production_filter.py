"""生产环境 CORS origin 过滤规则：https 一律放行；明文 HTTP 只放行 localhost/回环/内网 IP。

背景（2026-09-17）
----------------
`config.py` 原先在生产环境只保留 `https://*` 与 `http://localhost*`，于是**局域网 origin**
（如 `http://192.168.0.95:3000`）永远进不了 `BACKEND_CORS_ORIGINS`。该列表有两个消费方：

1. `CORSMiddleware.allow_origins` —— 跨域访问；
2. CSRF 中间件 `_is_allowed_origin` 的「Bearer + 无 cookie」Origin 校验分支
   —— 放不进去就必然 403「跨站请求被拒绝」。

本次放开：明文 HTTP 仅对 **localhost / 回环 / 内网 IP（10/8、172.16/12、192.168/16）** 放行；
**公网明文 HTTP 仍一律拒收**（生产不允许公网 http 源），域名形式的内网主机名也不放行。
"""
from __future__ import annotations

import pytest

from fastapi_app.core.config import filter_cors_origins

PROD = {"is_production": True}
DEV = {"is_production": False}


@pytest.mark.parametrize(
    "origin",
    [
        "http://192.168.0.95",          # 内网 IP 裸 origin
        "http://192.168.0.95:3000",     # nginx 前端入口（本次事故现场）
        "http://192.168.0.95:5002",     # 后端直连
        "http://10.0.0.8:3000",         # 10/8
        "http://172.16.5.5:3000",       # 172.16/12
        "http://localhost",             # 既有放行项
        "http://localhost:3000",
        "http://127.0.0.1:3000",        # 回环
        "https://erp.example.com",      # https 一律放行
    ],
)
def test_production_allows_lan_and_local_http(origin: str) -> None:
    assert origin in filter_cors_origins(origin, **PROD)


@pytest.mark.parametrize(
    "origin",
    [
        "http://evil.example.com",      # 公网域名 + 明文 HTTP ⇒ 拒收
        "http://8.8.8.8",               # 公网 IP + 明文 HTTP ⇒ 拒收
        "http://192.168.0.95.evil.com", # 仿冒内网前缀的域名 ⇒ 拒收（必须按 host 解析，不能 startswith）
        "http://erp.lan:3000",          # 内网域名但非 IP 字面量 ⇒ 保守拒收
    ],
)
def test_production_still_rejects_public_plain_http(origin: str) -> None:
    assert origin not in filter_cors_origins(origin, **PROD)


def test_development_is_permissive() -> None:
    raw = "http://localhost:3000,http://192.168.0.95:3000,http://evil.example.com"
    assert filter_cors_origins(raw, **DEV) == raw.split(",")


def test_keeps_order_and_drops_blanks() -> None:
    raw = "http://localhost:3000, ,http://192.168.0.95:3000,,https://erp.example.com"
    assert filter_cors_origins(raw, **PROD) == [
        "http://localhost:3000",
        "http://192.168.0.95:3000",
        "https://erp.example.com",
    ]


def test_real_settings_filter_applies_consistently() -> None:
    """真实 settings 对象必须按规则过滤 `_raw_cors`（防止类体装配被改坏）。

    这是**不依赖本机 `.env` 内容**的装配断言：对 raw 列表逐项校验
    「是否入选 BACKEND_CORS_ORIGINS」与规则判定一致。干净检出同样通过。
    """
    from fastapi_app.core.config import (
        _is_production_allowed_origin,
        _is_production_env,
        settings,
    )

    raw = settings._raw_cors  # type: ignore[attr-defined]
    is_prod = _is_production_env()
    entries = [o.strip() for o in raw.split(",") if o.strip()]
    for entry in entries:
        expected = _is_production_allowed_origin(entry) if is_prod else True
        assert (entry in settings.BACKEND_CORS_ORIGINS) is expected, (
            f"{entry!r} 入选结果与规则不一致（is_production={is_prod}）"
        )


def test_deployment_env_declares_lan_origin() -> None:
    """本机部署配置（`.env`）声明了局域网 origin 时，它必须能通过生产过滤存活。

    `.env` 不入库（见 .gitignore），干净检出时不存在 → 跳过，并明确说明原因，
    避免「用例静默通过但毫无意义」。本机为生产机，该断言会真实执行。
    """
    from fastapi_app.core.config import settings

    lan = "http://192.168.0.95:3000"
    raw = settings._raw_cors  # type: ignore[attr-defined]
    if lan not in raw:
        pytest.skip(
            f"当前 CORS_ORIGINS 未声明 {lan}（干净检出或非生产机），"
            f"跳过部署配置断言。当前值：{raw}"
        )
    assert lan in filter_cors_origins(raw, **PROD), "局域网 origin 被生产过滤规则丢掉了"
