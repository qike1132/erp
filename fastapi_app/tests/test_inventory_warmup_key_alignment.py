"""库存缓存「启动预热键」与「前端 /stock 默认分页键」必须一致。

背景（2026-10-13，用户报「服务器新启动后进 /stock 白屏 3~6 秒」）：
``fastapi_app/main.py::_warm_inventory_cache`` 在启动时预热库存缓存，目的就是让
「重启后第一次进 /stock」直接命中缓存。但 ``get_inventory_paginated`` 的缓存键由
``key_builder`` 用 ``(customer, product, page, per_page)`` 拼成：

    预热调用  per_page=20  →  键 ``…--1-20``
    前端默认  per_page=15  →  键 ``…--1-15``

两个键永不相等 —— 预热写进去的条目**从未被任何请求命中**，等于没预热。实测一次
冷缓存全量 CTE 要 4~5 秒（nginx access log 里 ``request_time=4.991``），用户看到的
就是「重启后进 /stock 白屏数秒」，且此后每 120s（缓存 TTL）重现一次。

本测试把「两处默认值一致」锁死：任一侧单独改动都会红。这不是同义反复 —— 两侧是
跨语言、跨文件的两个独立常量，历史上正是它们悄悄漂移才出的这个 bug。
"""
import ast
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MAIN_PY = _REPO_ROOT / "fastapi_app" / "main.py"
_INVENTORY_TAB = _REPO_ROOT / "frontend-vite" / "src" / "views" / "stock" / "InventoryTab.vue"


def _function_source(path: Path, name: str) -> str:
    """取出某个函数的源码段（用 AST 定位，避免正则误命中同名调用）。"""
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(src, node) or ""
    raise AssertionError(f"{path} 里找不到函数 {name}（预热是否已被重命名/删除？）")


def _warmup_per_page() -> int:
    body = _function_source(_MAIN_PY, "_warm_inventory_cache")
    match = re.search(r"per_page\s*=\s*(\d+)", body)
    assert match, "_warm_inventory_cache 里没有 per_page=<数字> 字面量"
    return int(match.group(1))


def _frontend_default_per_page() -> int:
    src = _INVENTORY_TAB.read_text(encoding="utf-8")
    match = re.search(r"const\s+perPage\s*=\s*ref\(\s*(\d+)\s*\)", src)
    assert match, "InventoryTab.vue 里没有 `const perPage = ref(<数字>)`"
    return int(match.group(1))


def test_warmup_per_page_matches_frontend_stock_default():
    warmup = _warmup_per_page()
    frontend = _frontend_default_per_page()
    assert warmup == frontend, (
        f"启动预热 per_page={warmup} 与前端 /stock 默认 per_page={frontend} 不一致 —— "
        "缓存键不同，预热条目永远不会被命中，重启后首次进 /stock 仍会冷缓存白屏数秒。"
        "改任一侧时请同步另一侧（fastapi_app/main.py::_warm_inventory_cache "
        "与 frontend-vite/src/views/stock/InventoryTab.vue 的 perPage）。"
    )
