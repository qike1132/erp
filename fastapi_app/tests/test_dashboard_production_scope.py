"""离线验证移动看板的部门、工厂及模块读取范围。"""
from dataclasses import replace
from secrets import token_urlsafe
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from fastapi_app.api.v1.endpoints.dashboard import get_mobile_dashboard
from fastapi_app.core import cache, database
from fastapi_app.core.production_scope import view_code
from fastapi_app.services.dashboard import activities, mobile, stats, todos
from fastapi_app.services.dashboard.scope import DashboardReadScope, dashboard_cache_key
from fastapi_app.shared_models import Permission, User

pytestmark = pytest.mark.asyncio
DATE = '2026-11-23'


@pytest.fixture(autouse=True)
def offline_cache(monkeypatch):
    cache.invalidate_local_cache('*')
    monkeypatch.setattr(cache, '_get_redis_cache', lambda: None)
    yield
    cache.invalidate_local_cache('*')


def _db():
    result = MagicMock()
    result.all.return_value = []
    result.one.return_value = SimpleNamespace(
        daily_qty=10, daily_amt=0, total_qty=10, total_amt=0, inv_qty=20, inv_amt=0,
        qty=0, amt=0, today_qty=0, today_amt=0, month_qty=0, month_amt=0,
    )
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    return db


def _user(*codes, factory='', is_super=False):
    user = User(username='dashboard_scope_test', password=token_urlsafe(24), factory=factory, is_super=is_super)
    user.permissions = [Permission(name=code, code=code) for code in codes]
    return user


def _sqls(db):
    return [str(c.args[0].compile(dialect=postgresql.dialect(), compile_kwargs={'literal_binds': True}))
            for c in db.execute.await_args_list]


@pytest.mark.parametrize('factory', ['东莞', '湖北'])
async def test_department_and_factory_apply_to_daily_and_month_fallback(factory):
    db = _db()
    response = await get_mobile_dashboard(DATE, 1, _user(view_code('filling'), factory=factory), db)
    daily, monthly = _sqls(db)
    assert all('daily_production_record' in sql for sql in (daily, monthly))
    assert all("department IN ('filling')" in sql for sql in (daily, monthly))
    assert all(f"product.factory = '{factory}'" in sql for sql in (daily, monthly))
    assert response.data.production.departments == []


async def test_aggregate_production_can_read_all_departments():
    db = _db()
    scope = DashboardReadScope.for_user(_user('production_summary_view'))
    await mobile.fetch_mobile_dashboard(DATE, db, scope)
    assert len(_sqls(db)) == 2
    for sql in _sqls(db):
        assert 'daily_production_record' in sql
        assert 'department IN' not in sql


async def test_empty_scope_returns_empty_cards_without_business_queries(monkeypatch):
    db = _db()
    monkeypatch.setattr(database, 'get_async_db_context', MagicMock(side_effect=AssertionError('不可取独立数据库会话')))
    user = _user('customer_manage')  # 无任何仪表盘来源权限的普通用户。
    scope = DashboardReadScope.for_user(user)
    response = await get_mobile_dashboard(DATE, 1, user, db)
    assert response.success is True
    assert response.data.production.model_dump() == {'total_value': 0.0, 'departments': []}
    assert response.data.orders.total_qty == 0
    assert response.data.production_plans == {'plans': [], 'monthly_summary': None}
    assert not any((await stats.fetch_dashboard_stats(db, scope)).values())
    assert await todos.fetch_dashboard_todos(db, scope) == {'success': True, 'data': []}
    assert await activities.fetch_dashboard_activities(db, scope) == []
    db.execute.assert_not_awaited()


async def test_amount_visibility_and_mobile_module_sql_are_independent():
    db = _db()
    user = _user('order_manage', 'stock_view', 'stockout_manage', 'case_manage', 'production_plan_view', factory='东莞')
    scope = DashboardReadScope.for_user(user)
    await mobile.fetch_mobile_dashboard(DATE, db, scope)
    statements = _sqls(db)
    assert len(statements) == 6
    assert all("product.factory = '东莞'" in sql for sql in statements)
    assert all('product.price' not in sql for sql in statements)
    assert any('purchase_plan_details.product_id' in sql for sql in statements)
    assert sum('"case".product_id = product.id' in sql for sql in statements) == 2

    amount_db = _db()
    await mobile.fetch_mobile_dashboard(DATE, amount_db, replace(scope, amounts=True))
    assert sum('product.price' in sql for sql in _sqls(amount_db)) == 5


async def test_mobile_cache_shares_only_identical_authorization(monkeypatch):
    l2 = {}
    fake_redis = SimpleNamespace(
        get=AsyncMock(side_effect=l2.get),
        set=AsyncMock(side_effect=lambda key, value, **_: l2.update({key: value})),
        redis_client=SimpleNamespace(set=AsyncMock(return_value=True), eval=AsyncMock()),
        _make_key=lambda key: key,
    )
    monkeypatch.setattr(cache, '_get_redis_cache', lambda: fake_redis)
    base = DashboardReadScope(factory='东莞', departments=('filling',))
    scopes = [base, replace(base, factory='湖北'), replace(base, departments=('handcraft',)), replace(base, orders=True)]
    for scope in scopes:
        cache.invalidate_local_cache('*')
        cold = _db()
        result = await mobile.fetch_mobile_dashboard(DATE, cold, scope)
        warm = _db()
        assert await mobile.fetch_mobile_dashboard(DATE, warm, scope) == result  # L1
        cache.invalidate_local_cache('*')
        assert await mobile.fetch_mobile_dashboard(DATE, warm, scope) == result  # L2
        assert cold.execute.await_count == (3 if scope.orders else 2)
        warm.execute.assert_not_awaited()
    assert len(l2) == len(scopes)
    assert dashboard_cache_key(scope=base, query_date=DATE) != dashboard_cache_key(scope=base, query_date='2026-11-24')
    assert dashboard_cache_key(scope=base) != dashboard_cache_key(scope=replace(base, departments=None))


async def test_superuser_retains_all_required_module_reads():
    scope = DashboardReadScope.for_user(_user(is_super=True, factory='东莞'))
    assert scope.factory == ''
    assert scope.departments is None
    assert all((scope.orders, scope.stockin, scope.stockout, scope.inventory, scope.warehouse,
                scope.plans, scope.purchases, scope.materials, scope.amounts))
