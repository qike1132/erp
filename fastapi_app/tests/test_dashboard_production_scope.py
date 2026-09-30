"""移动端看板生产卡片按用户部门范围收窄（R8 收口）。

覆盖：
- 服务层：departments 非 None 时，当日聚合与当月兜底查询都带 department IN；
  departments 为 None 时两者都不带（保持改动前的行为）。
- 端点层：v1/v2 移动看板把当前用户的部门范围下传给服务；
  无生产权限的用户拿到 200 与空生产卡片，而不是 403 拖垮整个看板。
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.core.deps import get_current_user_with_permissions
from fastapi_app.core.production_scope import view_code
from fastapi_app.main import app
from fastapi_app.services.dashboard.mobile import fetch_mobile_dashboard
from fastapi_app.shared_models import Permission, User


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------
def _capturing_db():
    """返回 (db, statements)：记录每条交给 session 的语句并返回空结果集。

    空结果集使当日聚合为空，从而触发当月兜底查询 —— 两个生产查询各执行一次。
    """
    statements = []

    async def _execute(stmt, *args, **kwargs):
        statements.append(stmt)
        result = MagicMock()
        result.all.return_value = []
        return result

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=_execute)
    return db, statements


def _production_statements(statements):
    """只挑出针对 daily_production_record 的语句（当日聚合 + 当月兜底）。"""
    return [s for s in statements if 'daily_production_record' in str(s).lower()]


def _perm(code):
    """真实游离态 Permission（同 test_production_scope_dependency.py 的做法）。"""
    perm = Permission(name=code, code=code)
    perm.parent_id = None
    return perm


def _user(codes, *, is_super=False):
    user = User(username='t_user', password='x')
    user.is_super = is_super
    user.permissions = [_perm(c) for c in codes]
    return user


def _dashboard_payload(departments):
    return {
        'success': True,
        'data': {
            'stock': {'today_quantity': 0, 'today_amount': 0.0, 'month_quantity': 0,
                      'month_amount': 0.0, 'total_quantity': 0, 'total_amount': 0.0},
            'production': {
                'total_value': sum(d['output_value'] for d in departments),
                'departments': departments,
            },
            'shipping': {'daily_qty': 0, 'total_amount': 0.0},
            'orders': {'daily_qty': 0, 'daily_amount': 0.0, 'total_amount': 0.0,
                       'total_qty': 0, 'total_inventory': 0, 'total_inventory_amount': 0.0},
            'warehouse': {'in_qty': 0, 'in_amount': 0.0, 'out_qty': 0, 'out_amount': 0.0},
            'production_plans': {},
        },
    }


@pytest.fixture(autouse=True)
def _no_redis():
    """关闭 Redis 层，缓存退化为进程内 L1，测试可确定性地断言 SQL 语句。"""
    with patch('fastapi_app.core.cache._get_redis_cache', return_value=None):
        yield


# ---------------------------------------------------------------------------
# 服务层：SQL 必须真实带部门过滤
# ---------------------------------------------------------------------------
class TestServiceScopeFilter:
    async def test_scoped_query_filters_today_and_month_fallback(self):
        db, statements = _capturing_db()
        await fetch_mobile_dashboard(None, db, departments={'filling'})

        prod_stmts = _production_statements(statements)
        assert len(prod_stmts) == 2, '应执行当日聚合与当月兜底各一次'
        assert 'department IN' in str(prod_stmts[0]), '当日聚合必须带部门过滤'
        assert 'department IN' in str(prod_stmts[1]), '当月兜底必须带部门过滤'

    async def test_unscoped_query_adds_no_department_filter(self):
        db, statements = _capturing_db()
        await fetch_mobile_dashboard(None, db, departments=None)

        prod_stmts = _production_statements(statements)
        assert len(prod_stmts) == 2
        for stmt in prod_stmts:
            assert 'department IN' not in str(stmt), '未收窄时不得出现部门过滤'


# ---------------------------------------------------------------------------
# 端点层：范围下传 + 无权限不 403
# ---------------------------------------------------------------------------
def _override_user(user):
    app.dependency_overrides[get_current_user_with_permissions] = lambda: user


class TestMobileDashboardEndpointScope:
    async def test_v1_scoped_user_receives_only_that_department(self, client):
        _override_user(_user([view_code('filling')]))
        payload = _dashboard_payload([
            {'name': '充棉部', 'daily_output': 10, 'output_value': 70.0},
        ])
        mock_fetch = AsyncMock(return_value=payload)
        with patch('fastapi_app.api.v1.endpoints.dashboard.fetch_mobile_dashboard', mock_fetch):
            resp = await client.get('/api/v1/dashboard/mobile')

        assert resp.status_code == 200
        assert mock_fetch.await_args.kwargs['departments'] == {'filling'}
        depts = resp.json()['data']['production']['departments']
        assert [d['name'] for d in depts] == ['充棉部']

    async def test_v1_user_without_production_permission_gets_empty_not_403(self, client):
        _override_user(_user([]))
        mock_fetch = AsyncMock(return_value=_dashboard_payload([]))
        with patch('fastapi_app.api.v1.endpoints.dashboard.fetch_mobile_dashboard', mock_fetch):
            resp = await client.get('/api/v1/dashboard/mobile')

        assert resp.status_code == 200, '无生产权限必须仍返回 200（空卡片），不得 403'
        assert mock_fetch.await_args.kwargs['departments'] == set()
        assert resp.json()['data']['production'] == {'total_value': 0.0, 'departments': []}

    async def test_v2_scoped_user_receives_only_that_department(self, client):
        _override_user(_user([view_code('handcraft')]))
        payload = _dashboard_payload([
            {'name': '手工部', 'daily_output': 5, 'output_value': 35.0},
        ])
        mock_fetch = AsyncMock(return_value=payload)
        with patch('fastapi_app.api.v2.endpoints.dashboard.fetch_mobile_dashboard', mock_fetch):
            resp = await client.get('/api/v2/dashboard/mobile')

        assert resp.status_code == 200
        assert mock_fetch.await_args.kwargs['departments'] == {'handcraft'}
        depts = resp.json()['data']['production']['departments']
        assert [d['name'] for d in depts] == ['手工部']
