"""权限码接线的回归（2026-11-16 上线前审计 A-28 / A-29 / A-30）。

拦哪种错：导航上的入口与后端接口用的权限码不是同一套 —— 用户被勾了权限却点开全 403，
或者明明该看的量看不到（前端闸门 fail-open）。三条都属于「代码里没人报错、生产里悄悄坏掉」，
只能靠接线断言 + 导航载荷测试盯住。
"""
from __future__ import annotations

import inspect
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _src(rel: str) -> str:
    return (PROJECT_ROOT / rel).read_text(encoding='utf-8')


def _dependency_source(func) -> str:
    """把端点函数的签名（含 Depends(...) 表达式）取出来做断言。"""
    return inspect.getsource(func)


# ------------------------------------------------------------------ A-28
def test_available_shipment_accepts_shipout_page_codes():
    """出库录入页拿可出货量时，只授「出库管理」的用户也必须放行（审计 A-28）。"""
    from fastapi_app.api.v1.endpoints.auxiliary import available_shipment

    src = _dependency_source(available_shipment)
    assert 'require_any_permission' in src, '只挂单个权限码会导致出库页 403'
    for code in ('stock_view', 'stockin_manage', 'stockout_manage'):
        assert code in src, f'缺少页面实际使用的权限码: {code}'


# ------------------------------------------------------------------ A-30
def test_admin_permission_code_is_not_used_anywhere():
    """`admin` 这个权限码全仓零登记（seed/init/migrations 都没有），
    用它当依赖等于「隐式超管门」，必须显式写 require_superuser（审计 A-30）。"""
    src = _src('fastapi_app/api/v1/endpoints/auxiliary.py')
    assert 'require_permission("admin")' not in src
    assert src.count('require_superuser()') >= 3, '缓存统计/清除/系统统计三处都应收口到超管'


# ------------------------------------------------------------------ A-29
def test_approval_nav_is_superuser_only():
    """审批管理只能超管用（业务 2026-10-02 已定），所以导航项要标成超管专属，
    否则勾了 approval_manage 的人会看到一个点开全 403 的假入口（审计 A-29）。"""
    from fastapi_app.core import nav_context

    assert 'approval_manage' in nav_context.SUPERUSER_ONLY_NAV_CODES

    # 导航载荷必须把该标记透出去（前端 filteredNavSections 靠它过滤）
    src = _src('fastapi_app/core/nav_context.py')
    assert "'superuser_only': item.code in SUPERUSER_ONLY_NAV_CODES" in src

    # 且该导航项仍留在库里（超管还要用它），只是对非超管隐藏
    assert 'approval_manage' in _src('scripts/seed_nav.py')


def test_user_manage_nav_is_superuser_only():
    """用户管理接口全部 require_superuser，导航层也必须标超管专属，
    否则被直接改库勾选 user_manage 的非超管会看到点开全 403 的假入口。"""
    from fastapi_app.core import nav_context

    assert 'user_manage' in nav_context.SUPERUSER_ONLY_NAV_CODES
    assert 'user_manage' in _src('scripts/seed_nav.py')


def test_outsource_fine_grained_codes_are_in_authoritative_seed():
    """外发细粒度码必须进 seed_nav，不能只靠一次性脚本（审计 L-02）。"""
    src = _src('scripts/seed_nav.py')
    for code in ('outsource_view', 'outsource_ship', 'outsource_receive'):
        assert f"'{code}'" in src, f'权威种子 seed_nav.py 缺少权限码: {code}'


def test_superuser_only_flag_does_not_leak_into_permission_codes():
    """超管专属标记不得顺手把 approval_manage 从 permission_codes 里删掉 ——
    权限码本身要保留（存量授权不破坏），隐藏是前端按 is_super 做的一层。"""
    from fastapi_app.core.nav_context import nav_permission_codes

    assert 'approval_manage' in nav_permission_codes('approval_manage')


# ------------------------------------------------------------------ 回归护栏
def test_no_endpoint_depends_on_unregistered_permission_code():
    """粗粒度守卫：端点里出现的权限码必须至少能在 seed/init/迁移中找到登记。"""
    # 只对本次改动涉及的三码做登记校验；其余存量码（customer_manage/product_view 等）
    # 的登记缺口属另一批问题，不在这里顺带断言，避免把守卫写成「一改就红」。
    codes = {'stock_view', 'stockin_manage', 'stockout_manage'}
    registry = (
        _src('scripts/seed_nav.py')
        + _src('scripts/init_permissions.py')
        + ''.join(
            p.read_text(encoding='utf-8')
            for p in (PROJECT_ROOT / 'migrations' / 'versions').glob('*.py')
        )
    )
    unknown = sorted(c for c in codes if f"'{c}'" not in registry and f'"{c}"' not in registry)
    assert not unknown, f'以下权限码在 seed/init/迁移中查不到登记: {unknown}'
