"""API 层 E2E —— 直连**真实运行的后端**，验证 views/** 依赖的接口真的能用。

为什么不复用现有三套测试
------------------------
本项目已有三处"看起来像端到端"的东西，但都存在真实盲区，本套件是补这些盲区的：

1. ``tests/qa/test_smoke.py``
   该文件已于 2026-10-03 收紧（登录失败显式断言、非豁免端点要求 200/201）；
   但它是进程内冒烟。本套件直连真实运行的后端，额外验证业务数据流真的通。

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

运行条件（2026-09-29 起）
------------------------
必须显式设置两个环境变量，否则整目录 skip 或 fail-fast：

- ``E2E_API_BASE_URL``：指向专用临时后端（禁止 5002 —— 生产）
- ``ERP_E2E_REAL_DATABASE_URL``：测试库 DSN（禁止 ``erp_system`` —— 生产库）

生产指纹命中时 ``pytest.exit(returncode=2)`` 终止整个会话，无绕过开关。
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
import typing
from pathlib import Path

import pytest
import pytest_asyncio

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import httpx

from fastapi_app.core.config import settings

# 必须显式指定目标后端；未设置时 BASE_URL 为 None，收集钩子整目录 skip。
# 绝不给默认值 127.0.0.1:5002 —— 那是生产后端（nginx upstream）。
BASE_URL: str | None = os.environ.get("E2E_API_BASE_URL")
if BASE_URL:
    BASE_URL = BASE_URL.rstrip("/")

# 真实库 URL —— 必须在**收集期**固化，不能等到用例运行期再读 settings。
#
# 原因：`tests/conftest.py` 的 `app_on_test_db`（session 级 autouse）会把
# `settings.DATABASE_URL` 重定向到 `erp_system_test`（空库），供 tests/ 下的
# 进程内 ASGI 套件使用。本目录不走那条路径（直连真实后端 HTTP），却同样继承
# 了那个 fixture —— 于是造数与 `_mint_token` 都打到空测试库：admin 查不到、
# 整个目录被 skip 成"绿"，P1 写入路径回归**从未真正执行过**。
#
# 为什么用环境变量而不是模块常量：本文件可能被 pytest（`import conftest`）与
# 业务代码（`from tests.e2e_api import conftest`）以**两个不同的模块身份**各
# 导入一次，后者发生在用例运行期（settings 已被改写）→ 模块常量会被算成空库。
# 环境变量是进程级的，且 autouse fixture 只改 settings 不碰 os.environ，故
# `setdefault` 能保证留下的一定是收集期的真实值。
_REAL_DB_ENV_KEY = "ERP_E2E_REAL_DATABASE_URL"
os.environ.setdefault(_REAL_DB_ENV_KEY, str(settings.DATABASE_URL))


def real_database_url() -> str:
    """真实后端所用库的同步 URL（收集期固化，见上方说明）。"""
    return os.environ[_REAL_DB_ENV_KEY]


def _mask_dsn(dsn: str) -> str:
    """隐去 DSN 中的口令，便于在失败信息里安全地指出「连的是哪个库」。"""
    from urllib.parse import urlparse, urlunparse

    try:
        parsed = urlparse(dsn)
        if parsed.password is None:
            return dsn
        netloc = parsed.netloc.replace(f":{parsed.password}@", ":***@")
        return urlunparse(parsed._replace(netloc=netloc))
    except ValueError:
        return "<unparsable-dsn>"


class _MintOutcome(typing.NamedTuple):
    """铸 token 的三态结果 —— 用于把「环境缺失」与「环境损坏」区分开。"""

    token: str | None
    db_reachable: bool

# 单请求超时。给足 20s：真实库上 dashboard/stats 这类聚合查询在冷缓存时较慢，
# 但 20s 仍未返回说明后端真的卡住了，应当失败而不是无限等待。
TIMEOUT = float(os.environ.get("E2E_API_TIMEOUT", "20"))


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "e2e_api: API 层端到端测试（需真实后端，未设置可达时整目录跳过）",
    )


# ============================================================
# 生产指纹守卫 —— 命中即拒绝运行（fail-fast，无绕过开关）
# ============================================================
def _production_fingerprint_hit(
    base_url: str | None = None,
    db_url: str | None = None,
) -> tuple[bool, str]:
    """目标命中生产指纹 → (True, 原因)。无绕过开关（fail-fast 是刻意的）。"""
    from urllib.parse import urlparse

    url = base_url if base_url is not None else BASE_URL
    dsn = db_url if db_url is not None else os.environ.get(_REAL_DB_ENV_KEY, "")

    if url:
        try:
            if urlparse(url).port == 5002:
                return True, f"E2E_API_BASE_URL 端口指向生产后端: {url}"
        except ValueError:
            pass
    try:
        if urlparse(dsn).path.lstrip('/') == 'erp_system':
            return True, "ERP_E2E_REAL_DATABASE_URL 指向生产库 erp_system"
    except ValueError:
        pass
    return False, ""


# 守卫自测文件：纯单测（不触网、不触库）。必须始终运行 —— 若被目录级 skip 连带跳过，
# 守卫本身将没有任何回归保护（CI/默认环境无后端，整目录 skip）。故按文件名白名单豁免。
_GUARD_TEST_FILE = "test_guard.py"

# 本 conftest 自身所在目录 —— 用于把 skip 标记限定在本目录的条目上（见下方说明）。
_E2E_DIR = Path(__file__).resolve().parent


def _item_path(item: pytest.Item) -> Path | None:
    """取 item 的源文件路径；``item.path``（现代 pytest）优先，回退 ``item.fspath``。"""
    path = getattr(item, "path", None)
    if path is None:
        fspath = getattr(item, "fspath", None)
        path = fspath if fspath is not None else None
    if path is None:
        return None
    try:
        return Path(path).resolve()
    except OSError:  # 路径无法解析（异常字符/权限）时退回未解析形式
        return Path(path)


def _skip_e2e_items(items: list[pytest.Item], reason: str) -> None:
    """给**本目录**的 E2E 用例打 skip 标记；豁免守卫自测（见 ``_GUARD_TEST_FILE``）。

    必须按路径过滤：``pytest_collection_modifyitems`` 在子目录 conftest 里被调用时，
    ``items`` 是**整个 pytest 会话**的条目列表，而非本目录的。若不加过滤，一次
    裸 ``pytest``（pytest.ini ``testpaths = tests fastapi_app/tests``）在未设
    ``E2E_API_BASE_URL`` 时会把**全仓每个用例**都打上 skip —— 包括本分支新增的
    numbering 测试，表现为"全绿"的假象。故只对路径确实位于本目录下的条目打标记。
    """
    skip = pytest.mark.skip(reason=reason)
    for item in items:
        path = _item_path(item)
        if path is None or _E2E_DIR not in path.parents:
            continue
        if path.name == _GUARD_TEST_FILE:
            continue
        item.add_marker(skip)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """未设置目标 → 整目录 skip；指纹命中 → 终止整个 pytest 会话；后端不可达 → 整目录 skip。

    顺序：**先判定「未设置 BASE_URL」**，再判定指纹。原因：``_REAL_DB_ENV_KEY`` 在收集期
    （本文件 ``setdefault``）已被固化为本机生产 DSN，若先判定指纹，则「默认环境」（未设任何
    E2E 变量）下的**任何** pytest 会话——包括 ``pytest tests/`` 全量与无关目录——都会
    ``pytest.exit(returncode=2)`` 直接中止。默认环境并没有 E2E 目标，整目录 skip 才是正确
    语义（对齐 spec §4.6「未设置 → 整目录 skip」）。

    指纹检查仍排在**探活**判断之前：否则「生产库在跑但后端探活失败」时先走 skip 分支、
    指纹守卫被短路。``pytest.exit`` 终止的是整个会话而非单目录 —— 有意为之的 fail-fast。
    """
    if not BASE_URL:
        _skip_e2e_items(items, "未设置 E2E_API_BASE_URL，跳过 API 层 E2E")
        return
    hit, reason = _production_fingerprint_hit()
    if hit:
        pytest.exit(
            f"拒绝运行 E2E：{reason}。E2E 不得指向生产。请同时设置 "
            "E2E_API_BASE_URL（非 5002 的临时后端）与 "
            "ERP_E2E_REAL_DATABASE_URL（测试库 DSN）。",
            returncode=2,
        )
    if _ALIVE:
        return
    _skip_e2e_items(
        items,
        (
            f"API 层 E2E 需要真实后端（{BASE_URL}），当前不可达：{_ALIVE_REASON}。"
            "请先启动专用后端并设置 E2E_API_BASE_URL"
        ),
    )


# ============================================================
# 后端可达性 —— 决定整个目录是"跑"还是"跳过"
# ============================================================
def _backend_alive() -> tuple[bool, str]:
    """探一次 /api/health。返回 (是否可用, 原因)。

    ``trust_env=False`` 是关键：本机存在 HTTP_PROXY，会把 127.0.0.1
    也代理走 → 502。契约工具踩过同一个坑，这里保持一致。
    """
    if not BASE_URL:
        return False, "E2E_API_BASE_URL 未设置"
    try:
        with httpx.Client(base_url=BASE_URL, timeout=5.0, trust_env=False) as client:
            resp = client.get("/api/health")
    except httpx.HTTPError as exc:
        return False, f"{type(exc).__name__}: {exc}"
    if resp.status_code != 200:
        return False, f"/api/health 返回 {resp.status_code}"
    return True, "ok"


_ALIVE, _ALIVE_REASON = _backend_alive()


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
def _mint_token(username: str = "admin") -> _MintOutcome:
    """现铸一个指定用户的 access token。

    与 ``scripts/contract_snapshot.py::mint_token`` 同源做法：
    查 user 表拿 id，再 ``create_access_token({'sub': str(uid)})``。
    口令可能被改，但 user 表的主键不会 —— 所以这条路径最稳。

    用收集期固化的 ``real_database_url()``（真实库），**不能**读
    ``settings.DATABASE_URL`` —— 后者已被 tests/conftest.py 的 autouse
    fixture 改成空测试库，见该函数处的说明。

    返回三态：能连库且查到用户 → token；能连库但查不到用户 → ``(None, True)``；
    连不上库 → ``(None, False)``。调用方据此决定 **skip 还是 fail** ——
    「库可达但 admin 不存在」是缺陷，不是环境缺失，绝不能静默跳过。
    """
    try:
        from sqlalchemy import create_engine, text

        from fastapi_app.core.auth.token import create_access_token

        engine = create_engine(real_database_url())
        with engine.connect() as conn:
            row = conn.execute(
                text('SELECT id FROM "user" WHERE username = :u'), {"u": username}
            ).fetchone()
        if row is None:
            return _MintOutcome(None, True)
        return _MintOutcome(create_access_token({"sub": str(row[0])}), True)
    except Exception:  # 连不上库属环境缺失，交由调用方 skip
        return _MintOutcome(None, False)


@pytest.fixture(scope="session")
def admin_token() -> str:
    outcome = _mint_token("admin")
    if outcome.token:
        return outcome.token

    if not outcome.db_reachable:
        pytest.skip(
            "无法连接数据库（无法铸 admin token）。"
            "请确认后端所用的库可直连。"
        )

    # 库连得上、admin 却查不到 —— 这是**缺陷**（或后端指向了另一个库），
    # 不是"环境缺失"。此处刻意 FAIL 而不是 skip：本目录曾因静默 skip
    # 把「P1 写入路径回归从未真正执行」隐藏成一片绿。
    pytest.fail(
        "数据库可达，但 user 表中不存在 username='admin'。"
        "请检查后端所用的库是否与本套件直连的是同一个"
        f"（当前: {_mask_dsn(real_database_url())}）。"
    )


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
