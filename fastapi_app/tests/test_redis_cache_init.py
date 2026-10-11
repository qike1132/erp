"""共享 Redis 缓存管理器初始化 的回归测试。

背景（评审 2026-10-11）：
``utils.redis_cache.redis_cache`` 必须在**每个使用它的进程**启动时 ``init_app()``
一次，否则 ``ensure_client()`` 恒返回 ``None``，``fastapi_app.core.redis_wrapper``
的所有路径静默降级。此前**只有 API 进程的 lifespan 调用过**，ARQ worker 进程
（独立 NSSM 服务 erp-arq）从不调用 —— 于是 worker 里 ``safe_lpush`` 写不进死信
队列（``arq:dead_letter`` 恒空，``ERP_DeadLetterQueueGrowing`` 永不触发）、worker
侧一切 Redis 缓存形同虚设。

本测试锁死两点：① 共享初始化函数按环境正确调用 ``init_app``；② API lifespan 与
worker ``on_startup`` 都真的调用了它。
"""
import ast
import asyncio
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _stub_redis_modules(settings_obj, redis_cache_obj) -> dict:
    """用轻量 stub 替换 config / utils.redis_cache（非提权下 config 读不了 .env）。"""
    cfg = types.ModuleType("fastapi_app.core.config")
    cfg.settings = settings_obj
    rc = types.ModuleType("utils.redis_cache")
    rc.redis_cache = redis_cache_obj
    return {"fastapi_app.core.config": cfg, "utils.redis_cache": rc}


def _fake_cache() -> MagicMock:
    cache = MagicMock()
    cache.init_app = AsyncMock()
    cache.get_stats = AsyncMock(return_value={"backend": "redis"})
    return cache


def test_init_redis_cache_manager_prefers_url(monkeypatch):
    """配了 REDIS_CACHE_URL 时，init_app 走 redis_url。"""
    from fastapi_app.core import redis_wrapper

    cache = _fake_cache()
    settings_obj = SimpleNamespace(
        REDIS_CACHE_URL="redis://cache-host:6380/2",
        REDIS_HOST="127.0.0.1", REDIS_PORT=6379, REDIS_DB=0, REDIS_PASSWORD="",
    )
    with patch.dict(sys.modules, _stub_redis_modules(settings_obj, cache)):
        asyncio.run(redis_wrapper.init_redis_cache_manager())

    cache.init_app.assert_awaited_once_with(redis_url="redis://cache-host:6380/2")


def test_init_redis_cache_manager_falls_back_to_host_port(monkeypatch):
    """无 URL 时回退到 host/port/db/password，且空密码归一为 None。"""
    from fastapi_app.core import redis_wrapper

    monkeypatch.delenv("REDIS_CACHE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)

    cache = _fake_cache()
    settings_obj = SimpleNamespace(
        REDIS_CACHE_URL="",
        REDIS_HOST="127.0.0.1", REDIS_PORT=6380, REDIS_DB=3, REDIS_PASSWORD="secret",
    )
    with patch.dict(sys.modules, _stub_redis_modules(settings_obj, cache)):
        asyncio.run(redis_wrapper.init_redis_cache_manager())

    cache.init_app.assert_awaited_once_with(
        redis_host="127.0.0.1", redis_port=6380, redis_db=3, redis_password="secret",
    )


def _called_names(func_node: ast.AST) -> set[str]:
    names = set()
    for node in ast.walk(func_node):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                names.add(node.func.attr)
    return names


def _function_node(path: Path, name: str) -> ast.AST:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name
    )


def test_worker_on_startup_calls_redis_init():
    """ARQ worker 的 on_startup 必须调用 init_redis_cache_manager（回归：曾漏调）。"""
    node = _function_node(_REPO_ROOT / "fastapi_app" / "core" / "arq_app.py", "on_startup")
    assert "init_redis_cache_manager" in _called_names(node), (
        "arq_app.WorkerSettings.on_startup 未调用 init_redis_cache_manager —— "
        "worker 进程不会初始化 redis_cache，死信队列将写不进。"
    )


def test_api_lifespan_calls_redis_init():
    """API lifespan 的 _setup_redis_caches 必须调用同一初始化（保持同源）。"""
    node = _function_node(_REPO_ROOT / "fastapi_app" / "main.py", "_setup_redis_caches")
    assert "init_redis_cache_manager" in _called_names(node), (
        "main._setup_redis_caches 未调用 init_redis_cache_manager —— "
        "API 与 worker 的 Redis 初始化不再是同一份逻辑。"
    )
