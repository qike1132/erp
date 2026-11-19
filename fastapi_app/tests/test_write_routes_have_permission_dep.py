"""每个**写路由**都必须有授权机制（审计 P2 3.1 的结构侧守卫）。

分工：
* `tests/test_write_endpoint_permission_denied.py` 证明「挑出来的几条写端点对非超管 403」；
* 本文件证明**全体**写路由都有授权依赖 —— 新增一个 POST/PUT/DELETE 却忘了
  `Depends(require_permission(...))`，会在这里当场红。

为什么不手抄端点清单：清单会随时间漂移，而路由树是唯一真相源。注意 `app.routes` 里挂的是
`_IncludedRouter` 包装（见 `docs/agents/pitfalls.md` §8），必须展开
`original_router.routes` 才能拿到真实 `APIRoute`；权限码挂在**递归**依赖树上
（`require_permission(...)` 产生的闭包带 `__permission_codes__`），不是顶层 dependant。

只认权限码会误判：有 11 个写路由用**另一种**授权机制（生产记录的 scope 校验、通知的
「仅本人」、认证/遥测端点）。它们必须逐条登记在这里**并写明理由** —— 这样「新增一个
没授权的写端点」要么缺权限码、要么得往这张表里加一行（评审可见），不会静默放行。
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.routing import APIRoute

from fastapi_app.main import app

WRITE_METHODS = frozenset({'POST', 'PUT', 'PATCH', 'DELETE'})

#: 没有权限码、但确实有其它授权机制的写路由（键 = (method, 路由相对 path)）。
#: 相对 path 与 `route.path` 一致（不含 `/api/v1` 前缀）。
ALLOWED_WITHOUT_PERMISSION_CODE: dict[tuple[str, str], str] = {
    ('POST', '/records'): '生产记录新增：resolve_production_write_scope 范围校验 + get_current_user_with_permissions',
    ('PUT', '/records/{record_id}'): '生产记录编辑：同上（部门/产品范围在端点内校验）',
    ('DELETE', '/records/{record_id}'): '生产记录删除：同上',
    ('POST', '/{notification_id}/read'): '通知已读：get_current_user_id，作用域天然是本人',
    ('POST', '/read-all'): '通知全部已读：同上',
    ('POST', '/login'): '认证入口：不可能要求权限码',
    ('POST', '/logout'): '认证出口：只需要 bearer',
    ('POST', '/refresh'): '令牌刷新：只需要 refresh_token',
    ('POST', '/logs/frontend-error'): '前端错误上报：get_current_user_id_write_strict（已登录即可）',
    ('POST', '/upload'): '通用文件上传：get_current_user_id_write_strict（资源级校验在调用方端点）',
    ('POST', '/vitals'): '前端性能指标上报：已登录即可，不涉业务数据',
}

#: 带权限码的写路由数量下限（2026-11-19 实测 192）。只允许上升：低于它说明
#: 「反射不到依赖」或「大量路由被摘掉了权限码」，两种都必须当场看见。
MIN_WRITE_ROUTES_WITH_CODES = 190


def _iter_api_routes(routes) -> list[APIRoute]:
    """展开 `_IncludedRouter` 包装，只留真实的 APIRoute。"""
    out: list[APIRoute] = []
    for route in routes:
        inner = getattr(route, 'original_router', None)
        if inner is not None:
            out.extend(_iter_api_routes(inner.routes))
            continue
        if isinstance(route, APIRoute):
            out.append(route)
    return out


def _permission_codes(dependant, acc: list[str] | None = None) -> list[str]:
    """递归收集依赖树上的 `__permission_codes__`。"""
    acc = [] if acc is None else acc
    call = getattr(dependant, 'call', None)
    acc.extend(getattr(call, '__permission_codes__', ()) or ())
    for sub in getattr(dependant, 'dependencies', []) or []:
        _permission_codes(sub, acc)
    return acc


def _write_routes(application: FastAPI) -> list[tuple[str, str, list[str]]]:
    rows: list[tuple[str, str, list[str]]] = []
    for route in _iter_api_routes(application.routes):
        methods = (getattr(route, 'methods', set()) or set()) & WRITE_METHODS
        if not methods:
            continue
        codes = _permission_codes(route.dependant)
        for method in sorted(methods):
            rows.append((method, route.path, codes))
    return rows


def test_every_write_route_has_an_authorization_mechanism():
    rows = _write_routes(app)

    without_codes = {(method, path) for method, path, codes in rows if not codes}
    unexpected = sorted(without_codes - set(ALLOWED_WITHOUT_PERMISSION_CODE))
    assert unexpected == [], (
        '这些写端点既没有权限码依赖、也没有在 ALLOWED_WITHOUT_PERMISSION_CODE 里登记理由：'
        f'{unexpected} —— 很可能是漏挂 Depends(require_permission(...))'
    )

    stale = sorted(set(ALLOWED_WITHOUT_PERMISSION_CODE) - without_codes)
    assert stale == [], (
        f'豁免表里有已失效条目（这些路由现在有权限码或已不存在）：{stale} —— 请删掉，'
        '否则豁免表会越攒越大，最后没人敢动'
    )


def test_write_route_coverage_floor():
    """扫描面下限：反射不到依赖、或大量路由被摘掉权限码时，上面的断言会「空集也通过」。"""
    rows = _write_routes(app)
    with_codes = [row for row in rows if row[2]]
    assert len(with_codes) >= MIN_WRITE_ROUTES_WITH_CODES, (
        f'带权限码的写路由只剩 {len(with_codes)} 条（下限 {MIN_WRITE_ROUTES_WITH_CODES}）：'
        '要么 _IncludedRouter 展开失效（反射不到依赖），要么权限码被批量摘掉'
    )
