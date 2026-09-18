"""回归护栏：`/api/health/arq` 专用健康端点（2026-09-17 审计 S3）。

背景：`erp-arq` 是**定时备份的唯一调度者**，但在此之前 ARQ 掉线**没有任何对外信号**
（`/api/health` 只查 DB+Redis，依旧返回 healthy）⇒ 数据保护可静默失效。

本护栏要守住的**核心不变量是「三态可区分」**：
  running       → 200
  not_running   → 503（键不存在 ⇒ worker 确实不在线）
  probe_unknown → 503（**探测自身**失败，如连不上 broker）—— 必须与 not_running 在文案上可区分，
                  否则会把运维引向「重启一个正常的 worker」而忽略真正出问题的 broker。

⚠️ 替身纪律（本仓有实证教训）：被测函数依赖的是 `check_worker_health()` 的**真实返回值形状**
（`tuple[bool, str]`），因此这里用**真实 async 函数**而非 `AsyncMock` —— `AsyncMock` 会自动合成
不存在的属性/返回值，把「契约不符」变成静默通过。
"""

import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI

from fastapi_app.core.health import register_health_routes

ARQ_PATH = "/api/health/arq"


def _app() -> FastAPI:
    app = FastAPI()
    register_health_routes(app)
    return app


async def _get(path: str) -> tuple[int, dict]:
    app = _app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(path)
        return resp.status_code, json.loads(resp.content.decode("utf-8"))


def _patch(monkeypatch, impl) -> None:
    """把 arq_app.check_worker_health 换成给定的 async 实现。

    端点在函数体内 `from fastapi_app.core.arq_app import check_worker_health`，
    因此补丁打在模块属性上即可生效（调用时才解析）。
    """
    monkeypatch.setattr(
        "fastapi_app.core.arq_app.check_worker_health", impl, raising=True
    )


@pytest.mark.parametrize(
    "impl_result,expected_status,expected_state",
    [
        # ① 在线
        ((True, "ARQ Worker 在线（Sep-17 22:37:48 j_failed=0）"), 200, "running"),
        # ② 确实未运行（键不存在）
        ((False, "ARQ Worker 未运行，请启动 erp-arq 服务"), 503, "not_running"),
        # ③ 探测自身超时 —— 关键：绝不能折算成 not_running
        (
            (False, "ARQ Worker 健康探测超时（>2s），请检查 erp-redis-broker 服务"),
            503,
            "probe_unknown",
        ),
        # ④ 探测自身异常
        ((False, "ARQ Worker 健康检测失败: ConnectionError"), 503, "probe_unknown"),
    ],
)
def test_arq_endpoint_three_states(monkeypatch, impl_result, expected_status, expected_state):
    async def fake():
        return impl_result

    _patch(monkeypatch, fake)
    status, body = asyncio.run(_get(ARQ_PATH))
    assert status == expected_status, body
    assert body["status"] == expected_state, body
    # 文案必须透传，便于排障（且是区分三态的依据）
    assert body["message"] == impl_result[1]


def test_probe_unknown_is_not_conflated_with_not_running(monkeypatch):
    """反例守卫：探测失败的文案**不得**被判定为 not_running。

    若将来有人把分流逻辑改坏（例如统一返回 not_running），本用例必须变红。
    """
    async def probe_failed():
        return (False, "ARQ Worker 健康探测超时（>2s），请检查 erp-redis-broker 服务")

    _patch(monkeypatch, probe_failed)
    _, body = asyncio.run(_get(ARQ_PATH))
    assert body["status"] == "probe_unknown"
    assert body["status"] != "not_running"


def test_probe_itself_raising_is_contained(monkeypatch):
    """探测自身抛异常时端点不得 500：必须转成 probe_unknown（健康探测不得抛出）。"""

    async def boom():
        raise RuntimeError("redis client exploded")

    _patch(monkeypatch, boom)
    status, body = asyncio.run(_get(ARQ_PATH))
    assert status == 503, body
    assert body["status"] == "probe_unknown"
    assert "RuntimeError" in body["message"]


def test_existing_health_endpoints_untouched():
    """/api/health/live 仍不依赖任何外部组件（证明本次改动是纯增量）。"""
    status, body = asyncio.run(_get("/api/health/live"))
    assert status == 200
    assert body["status"] == "alive"
