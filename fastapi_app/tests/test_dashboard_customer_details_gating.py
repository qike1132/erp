"""AUD-04（2026-10-24 审计）回归锁：dashboard 客户金额明细端点收敛。

原先 /dashboard/customer-out-details 与 /customer-order-details 仅登录即可读
（get_current_user_id），返回两厂全量、按客户营收金额；与本仓自身契约矛盾
（/reports/* 要求 report_view + 工厂隔离，/stock/stats 同类问题已修过）。

修复后（本文件锁定）：
- 无 report_view 的登录用户 → 403（并记 access_denied）；
- 有 report_view 且厂绑定的用户 → 服务层收到 factory 参数（查询带本厂过滤）；
- 超管不受工厂隔离（与 /reports 口径一致）；
- 服务层 fetch_customer_* 的 factory 维度进缓存键（厂 A 不得命中厂 B 的缓存）。

HTTP 断言使用根 conftest 的异步 client fixture（base_url 与 TrustedHost 白名单
匹配、自带 CSRF 头）；require_permission 内部 Depends 的是私有
_get_user_with_permissions，dependency_overrides 按函数对象键 override 私有名。
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from fastapi_app.core import deps as deps_mod
from fastapi_app.main import app
from fastapi_app.services.dashboard import customer as customer_svc
from fastapi_app.shared_models import Permission, User


def _perm(code):
    perm = Permission(name=code, code=code)
    perm.parent_id = None
    return perm


def _user(codes, *, factory='', is_super=False):
    user = User(username='t_user', password='x', factory=factory)
    user.is_super = is_super
    user.permissions = [_perm(c) for c in codes]
    return user


def _override_user(user):
    app.dependency_overrides[deps_mod._get_user_with_permissions] = lambda: user
    return user


@pytest.fixture
def _clean_overrides():
    yield
    app.dependency_overrides.pop(deps_mod._get_user_with_permissions, None)


async def test_customer_out_details_requires_report_view(client, _clean_overrides):
    """无 report_view 的登录用户必须 403（原先登录即可读逐客户金额——AUD-04）。"""
    for user in (_user(['stockin_manage']), _user([])):
        _override_user(user)
        resp = await client.get('/api/v1/dashboard/customer-out-details')
        assert resp.status_code == 403, f'用户 {user.permissions} 不应可读客户金额明细'


async def test_customer_order_details_requires_report_view(client, _clean_overrides):
    _override_user(_user(['order_manage']))
    resp = await client.get('/api/v1/dashboard/customer-order-details')
    assert resp.status_code == 403


async def test_factory_bound_user_passes_factory_to_service(
    client, _clean_overrides, monkeypatch,
):
    """厂绑定 + report_view：服务层必须收到本厂 factory（隔离在查询内）。"""
    captured = {}

    async def _fake_fetch(period, query_date, db, factory=''):
        captured['factory'] = factory
        return {'success': True, 'data': []}

    monkeypatch.setattr(
        'fastapi_app.api.v1.endpoints.dashboard.fetch_customer_out_details', _fake_fetch)
    _override_user(_user(['report_view'], factory='东莞'))
    resp = await client.get('/api/v1/dashboard/customer-out-details')
    assert resp.status_code == 200
    assert captured.get('factory') == '东莞', '厂绑定用户必须把本厂下传给服务层'


async def test_super_user_gets_unscoped_factory(client, _clean_overrides, monkeypatch):
    """超管不受工厂隔离（与 /reports 口径一致）。"""
    captured = {}

    async def _fake_fetch(period, date_param, db, factory=''):
        captured['factory'] = factory
        return {'success': True, 'data': []}

    monkeypatch.setattr(
        'fastapi_app.api.v1.endpoints.dashboard.fetch_customer_order_details', _fake_fetch)
    _override_user(_user(['report_view'], factory='东莞', is_super=True))
    resp = await client.get('/api/v1/dashboard/customer-order-details')
    assert resp.status_code == 200
    assert captured.get('factory') == ''


def test_cache_key_includes_factory_dimension():
    """factory 必须进缓存键：厂 A 的结果不得被厂 B 命中。"""
    k1 = customer_svc._customer_cache_key('period', 'query_date', period='today',
                                          query_date='', factory='东莞')
    k2 = customer_svc._customer_cache_key('period', 'query_date', period='today',
                                          query_date='', factory='湖北')
    k3 = customer_svc._customer_cache_key('period', 'query_date', period='today',
                                          query_date='', factory='')
    assert k1 != k2 != k3, 'factory 维度必须区分缓存键'
    assert k1.endswith('f:东莞')


def test_service_factory_filter_appended_to_query():
    """服务层：factory 非空时查询必须带 Product.factory 过滤（静态语句断言）。"""
    captured = []

    async def _execute(stmt, *a, **k):
        captured.append(stmt)
        result = MagicMock()
        result.all.return_value = []
        return result

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=_execute)

    import asyncio
    asyncio.run(customer_svc.fetch_customer_out_details(
        'today', None, db, factory='东莞'))
    assert 'factory' in str(captured[0]), 'factory 过滤必须出现在查询里'
    # 无 factory 时不加过滤（全员/超管口径不变）
    captured.clear()
    asyncio.run(customer_svc.fetch_customer_out_details('today', None, db))
    assert 'product.factory' not in str(captured[0]).lower()
