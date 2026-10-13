"""权限依赖工厂的 ``__permission_codes__`` 契约 + 全应用路由声明审计。

背景：``core/deps.py`` 的 ``require_permission`` / ``require_any_permission`` 在返回
依赖前，把声明的权限码挂到依赖函数上（``__permission_codes__``）。此前测试要拿
「某路由声明了哪些权限码」只能扒 ``dep.call.__closure__`` 的单元格内容——闭包单元格的
顺序与存在性是 CPython 实现细节，改工厂即失效。本文件把该属性立为契约，并做一次
全应用审计：任何挂了权限依赖的路由，声明的权限码都必须非空。

为什么「非空」值得单独设卡：``require_any_permission()`` 传空集会走 ``any(())``
恒为 False 的 fail-closed 分支，**拒绝所有非超管用户**（见该工厂 docstring）。
挂上该属性后，这种误用就能被静态扫出来，不必等某个用户报 403。
"""
from __future__ import annotations

import pytest

from fastapi_app.core.deps import require_any_permission, require_permission
from fastapi_app.main import app


def test_require_permission_exposes_single_code() -> None:
    checker = require_permission('product_manage')
    assert checker.__permission_codes__ == ('product_manage',)


def test_require_any_permission_exposes_all_codes() -> None:
    checker = require_any_permission('order_manage', 'stockout_manage')
    assert checker.__permission_codes__ == ('order_manage', 'stockout_manage')


def test_factories_do_not_share_declared_codes() -> None:
    """两个工厂各自挂自己的码，互不串味（属性挂在各自的函数对象上）。"""
    single = require_permission('a_code')
    multi = require_any_permission('b_code', 'c_code')
    assert single.__permission_codes__ == ('a_code',)
    assert multi.__permission_codes__ == ('b_code', 'c_code')


def _iter_api_routes():
    """展开 app 的全部业务路由。

    FastAPI 0.137 的 ``include_router`` 是惰性的：业务路由被包在 ``_IncludedRouter``
    壳里，壳自身没有 ``.routes`` / ``.dependant``，只扫 ``app.routes`` 会得到空集合
    （见 docs/agents/pitfalls.md §8）。故这里同时展开 ``.routes`` 与
    ``_IncludedRouter.original_router.routes``。
    """
    seen: set[int] = set()
    stack = list(app.routes)
    while stack:
        route = stack.pop()
        if id(route) in seen:
            continue
        seen.add(id(route))
        shell = getattr(route, 'original_router', None)  # _IncludedRouter 壳
        if shell is not None:
            stack.extend(getattr(shell, 'routes', []) or [])
            continue
        children = getattr(route, 'routes', None)
        if children:
            stack.extend(children)
            continue
        yield route


def _declared_codes(route):
    """产出该路由上所有权限依赖声明的权限码元组。"""
    dependant = getattr(route, 'dependant', None)
    for dep in getattr(dependant, 'dependencies', []) or []:
        codes = getattr(getattr(dep, 'call', None), '__permission_codes__', None)
        if codes is not None:
            yield codes


def test_every_permission_gated_route_declares_non_empty_codes() -> None:
    """全应用审计：凡挂了权限依赖的路由，声明的权限码必须非空且都是非空字符串。

    这条同时兜住两类退化：
    * 未来某个端点写了 ``require_any_permission()``（空参）——会拒绝所有人；
    * 工厂被改坏、属性挂成了空元组或 None。

    覆盖边界：只扫**路由自身**的顶层依赖（``route.dependant.dependencies``）。
    挂在 ``include_router(..., dependencies=[Depends(require_permission(...))])``
    上的权限依赖不在其中，审计看不见。本仓当前 include 级依赖全是
    ``get_current_user_id(_strict)``（无该属性），故暂无缺口；若将来把权限依赖
    上提到 include 层，需改为展开 ``_IncludedRouter.effective_candidates()``，
    否则这条审计会静默漏掉。
    """
    gated = 0
    offenders: list[tuple[str, object]] = []
    for route in _iter_api_routes():
        for codes in _declared_codes(route):
            gated += 1
            if not codes or not all(isinstance(c, str) and c for c in codes):
                offenders.append((getattr(route, 'path', '?'), codes))
    # 护栏：若路由遍历失效（扫不到任何权限依赖），下面的断言会恒真——先拦住这种假绿。
    assert gated > 0, '未扫到任何权限依赖——路由遍历可能失效（见 docs/agents/pitfalls.md §8）'
    assert not offenders, f'权限码为空的路由（require_any_permission() 无参会拒绝所有人）: {offenders}'


@pytest.mark.parametrize('factory', [require_permission, require_any_permission])
def test_empty_declaration_is_recorded_faithfully(factory) -> None:
    """``require_any_permission()`` 空参是误用：属性必须**如实**暴露成空元组，
    这样上面的路由审计才能把它扫出来（若属性把空参藏起来，审计就漏了）。"""
    if factory is require_permission:
        checker = factory('')
        assert checker.__permission_codes__ == ('',)
    else:
        checker = factory()
        assert checker.__permission_codes__ == ()
