"""API 层 E2E —— 直连**真实运行的后端**，验证 views/** 依赖的接口真的能用。

为什么不复用现有三套测试
------------------------
本项目已有三处"看起来像端到端"的东西，但都存在真实盲区，本套件是补这些盲区的：

1. ``tests/qa/test_smoke.py``
   断言是 ``status_code in (200, 201, 403, 401)`` —— **401 也算通过**。
   于是一个端点因 500 崩溃、或路由被误删（404）确实会被抓到，但如果
   鉴权依赖被写错导致所有请求都 401，冒烟测试会**全绿**。
   本套件要求鉴权端点必须 200，且必须返回真实业务数据。

2. ``tests/contract/``
   只覆盖 21 个只读 GET 端点，且只比对**结构签名**（键路径 + 类型），
   不验证"数据流是否真的通"（比如分页参数是否生效、筛选是否真的过滤了）。
   它是"防响应形态漂移"的门禁，不是端到端验证。

3. ``tests/e2e/test_e2e_order_flow.py``
   依赖 selenium + Chrome，CI 里被 ``--ignore=tests/e2e`` 排除 —— 等于不存在。

本套件补的正是「**鉴权后接口真的返回正确数据**」这一层。

设计取舍：为什么是 API 层而不是浏览器层
--------------------------------------
浏览器级 E2E（Playwright）能覆盖渲染与交互，但成本是：
需要下载浏览器（~300MB）、需要跑起前端 dev server、需要真实账号密码、
选择器易碎（本项目 views/** 有 166 个 .vue，56% 的源码体量）。
在本项目"本地自用、单人维护"的前提下，先用 API 层 E2E 拿住
**最高价值的失效模式**：接口挂了 / 鉴权坏了 / 分页筛选不生效 /
跨模块数据不一致 —— 这些占线上故障的绝大多数，且 API 层测试稳定得多。

运行条件
--------
需要一个**真实运行的后端**（不是 ASGITransport 进程内 app）：

    python scripts/restart_backend.py          # 或任何方式起 5002
    pytest tests/e2e_api -v

目标地址取 ``E2E_API_BASE_URL`` 环境变量，默认 ``http://127.0.0.1:5002``。
后端不可达时**整目录跳过**（跳过是正确行为，不是失败）—— 与
``tests/contract`` 的既有约定一致。

鉴权
----
本套件**不需要知道任何账号密码**：直接用 ``create_access_token``
现铸管理员 token（与 ``scripts/contract_snapshot.py`` 同一套做法）。
原因：真实库里的 admin 口令可能被改过（本项目实际就改过），
依赖口令会让套件在"口令变了"时全红 —— 那是误报，不是缺陷。

之所以还要保留"登录接口"的单测，是因为登录链路本身也要验证，
但那只在 ``test_auth_flow.py`` 里用**现造一个临时用户**的方式做，不影响其他用例。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import httpx  # noqa: E402

from fastapi_app.core.config import settings  # noqa: E402

BASE_URL = os.environ.get("E2E_API_BASE_URL", "http://127.0.0.1:5002").rstrip("/")

# 单请求超时。给足 20s：真实库上 dashboard/stats 这类聚合查询在冷缓存时较慢，
# 但 20s 仍未返回说明后端真的卡住了，应当失败而不是无限等待。
TIMEOUT = float(os.environ.get("E2E_API_TIMEOUT", "20"))


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "e2e_api: API 层端到端测试（需真实后端，未设置可达时整目录跳过）",
    )


# ============================================================
# 后端可达性 —— 决定整个目录是"跑"还是"跳过"
# ============================================================
def _backend_alive() -> tuple[bool, str]:
    """探一次 /api/health。返回 (是否可用, 原因)。

    ``trust_env=False`` 是关键：本机存在 HTTP_PROXY，会把 127.0.0.1
    也代理走 → 502。契约工具踩过同一个坑，这里保持一致。
    """
    try:
        with httpx.Client(base_url=BASE_URL, timeout=5.0, trust_env=False) as client:
            resp = client.get("/api/health")
    except httpx.HTTPError as exc:
        return False, f"{type(exc).__name__}: {exc}"
    if resp.status_code != 200:
        return False, f"/api/health 返回 {resp.status_code}"
    return True, "ok"


_ALIVE, _ALIVE_REASON = _backend_alive()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """后端不可达时跳过本目录所有用例，并说明原因与恢复方式。"""
    if _ALIVE:
        return
    skip = pytest.mark.skip(
        reason=(
            f"API 层 E2E 需要真实后端（{BASE_URL}），当前不可达：{_ALIVE_REASON}。"
            "请先启动后端：python scripts/restart_backend.py"
        )
    )
    for item in items:
        item.add_marker(skip)


# ============================================================
# HTTP 客户端
# ============================================================
@pytest_asyncio.fixture
async def api() -> httpx.AsyncClient:
    """无鉴权客户端 —— 用于验证 401 契约与公开端点。

    刻意用 **function scope**：session scope 的 async fixture 在
    pytest-asyncio 下需要 ``loop_scope="session"`` 配套（本项目
    pytest.ini 设的是 ``asyncio_default_fixture_loop_scope = function``），
    否则报 ScopeMismatch。而本套件每个用例只是一个 HTTP 往返，
    客户端建连开销可忽略 —— 不值得为省这点开销引入 loop 语义复杂度。
    """
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT, trust_env=False) as client:
        yield client


# ============================================================
# Token 铸造（不依赖任何口令）
# ============================================================
def _mint_token(username: str = "admin") -> str | None:
    """现铸一个指定用户的 access token。

    与 ``scripts/contract_snapshot.py::mint_token`` 同源做法：
    查 user 表拿 id，再 ``create_access_token({'sub': str(uid)})``。
    口令可能被改，但 user 表的主键不会 —— 所以这条路径最稳。
    """
    try:
        from sqlalchemy import create_engine, text

        from fastapi_app.core.auth.token import create_access_token

        engine = create_engine(settings.DATABASE_URL)
        with engine.connect() as conn:
            row = conn.execute(
                text('SELECT id FROM "user" WHERE username = :u'), {"u": username}
            ).fetchone()
        if row is None:
            return None
        return create_access_token({"sub": str(row[0])})
    except Exception:  # noqa: BLE001 - 铸 token 失败应让用例失败并说明，而非中断收集
        return None


@pytest.fixture(scope="session")
def admin_token() -> str:
    token = _mint_token("admin")
    if not token:
        pytest.skip(
            "无法读到 admin 用户（数据库不可达或 admin 不存在）。"
            "请确认后端所用的库可直连，或检查 user 表中是否存在 username='admin'。"
        )
    return token


@pytest.fixture(scope="session")
def admin_headers(admin_token: str) -> dict[str, str]:
    """管理员认证头 —— 本套件绝大多数用例用它。"""
    return {"Authorization": f"Bearer {admin_token}"}


@pytest_asyncio.fixture
async def admin_api(api: httpx.AsyncClient, admin_headers: dict[str, str]) -> httpx.AsyncClient:
    """带管理员鉴权的客户端。

    在同一个 ``api`` 客户端上注入 Authorization header，用完还原 ——
    这样 401 用例（不带 header）与 200 用例（带 header）语义清晰，
    也不需要为两种身份各建一个连接池。
    """
    api.headers.update(admin_headers)
    try:
        yield api
    finally:
        api.headers.pop("Authorization", None)
