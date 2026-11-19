"""写路由反射（唯一实现）：展开 `_IncludedRouter`、累积 include 前缀、收集权限码与依赖函数名。

2026-11-19 推送前评审的两个 Medium 根因都在这里：

1. 原来用 `route.path` 当键，但被 `include_router` 挂载后 `route.path` **不含 include 前缀** ——
   4 个 `/upload`（auth / ocr-import / purchase-plan / production-plan）当时塌成同一个键
   `('POST', '/upload')`，豁免表里一行替四条挡枪：只要其中一个 upload 被降级成「登录即可」，
   守卫仍然绿。`docs/agents/pitfalls.md` 早已写明「不能靠裸路径识别端点」。
2. 豁免表只有字符串理由（『resolve_production_write_scope 范围校验』），没有任何断言校验
   那个机制真的在依赖树上 —— 把依赖删掉，豁免理由还成立。这里把 `call_names` 暴露出去，
   让理由可以判定。

放在 `fastapi_app/tests/` 而不是两棵树各一份：`tests/test_write_endpoint_permission_denied.py`
（行为层）与 `fastapi_app/tests/test_write_routes_have_permission_dep.py`（结构层）都要用，
两份实现必然漂移。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from fastapi.routing import APIRoute

#: 视为「写」的 HTTP 方法。
WRITE_METHODS = frozenset({'POST', 'PUT', 'PATCH', 'DELETE'})


@dataclass(frozen=True)
class WriteRoute:
    """一条写路由：方法是展开后的单个方法，path 是**含 include 前缀**的完整模板路径。"""

    method: str
    path: str
    codes: tuple[str, ...]
    call_names: frozenset[str]


def _iter_routes(routes, prefix: str = ''):
    """递归展开 `_IncludedRouter` 壳，累积每一层的 `include_context.prefix`。"""
    for route in routes:
        inner = getattr(route, 'original_router', None)
        if inner is not None:
            ctx = getattr(route, 'include_context', None)
            yield from _iter_routes(inner.routes, prefix + (getattr(ctx, 'prefix', '') or ''))
            continue
        if isinstance(route, APIRoute):
            yield route, prefix


def _walk_dependant(dependant, visit) -> None:
    visit(dependant)
    for sub in getattr(dependant, 'dependencies', []) or []:
        _walk_dependant(sub, visit)


def permission_codes(dependant) -> tuple[str, ...]:
    """递归收集依赖树上的 `__permission_codes__`（保持出现顺序，便于失败信息阅读）。"""
    acc: list[str] = []

    def visit(node) -> None:
        acc.extend(getattr(getattr(node, 'call', None), '__permission_codes__', ()) or ())

    _walk_dependant(dependant, visit)
    return tuple(acc)


def dependant_call_names(dependant) -> frozenset[str]:
    """依赖树上所有可调用对象的 `__name__` —— 用来判定「另一种授权机制」真的挂了没。"""
    names: set[str] = set()

    def visit(node) -> None:
        name = getattr(getattr(node, 'call', None), '__name__', None)
        if name:
            names.add(name)

    _walk_dependant(dependant, visit)
    return frozenset(names)


def write_routes(application: Any) -> list[WriteRoute]:
    """整棵路由树里的写路由，按 (path, method) 排序，结果可直接做集合比较。"""
    out: list[WriteRoute] = []
    for route, prefix in _iter_routes(application.routes):
        methods = (getattr(route, 'methods', set()) or set()) & WRITE_METHODS
        if not methods:
            continue
        codes = permission_codes(route.dependant)
        names = dependant_call_names(route.dependant)
        for method in sorted(methods):
            out.append(
                WriteRoute(
                    method=method,
                    path=prefix + route.path,
                    codes=codes,
                    call_names=names,
                )
            )
    return sorted(out, key=lambda row: (row.path, row.method))


def path_template_matches(template: str, url: str) -> bool:
    """把 `/a/{id}/b` 这样的模板与具体 URL 比对（路径参数一律放宽成单段）。"""
    parts = re.split(r'\{[^}]+\}', template)
    return re.match('^' + '[^/]+'.join(re.escape(p) for p in parts) + '$', url) is not None


def codes_for_request(application: Any, method: str, url: str) -> tuple[str, ...] | None:
    """给定「具体方法 + 具体 URL」，返回该路由的权限码；路由不存在返回 None。"""
    for row in write_routes(application):
        if row.method == method and path_template_matches(row.path, url):
            return row.codes
    return None
