"""使用离线会话验证仪表盘工厂过滤及可见来源。"""
from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from fastapi_app.core import cache as cache_mod
from fastapi_app.core import database, redis_wrapper
from fastapi_app.services.dashboard import activities, stats, todos
from fastapi_app.services.dashboard.scope import DashboardReadScope

DT = datetime(2026, 11, 23)


@pytest.fixture(autouse=True)
def offline_cache(monkeypatch):
    cache_mod.invalidate_local_cache('*')
    monkeypatch.setattr(cache_mod, '_get_redis_cache', lambda: None)
    yield
    cache_mod.invalidate_local_cache('*')


def _db(*, today=5, yesterday=3):
    result = MagicMock()
    result.one.return_value = SimpleNamespace(today=today, yesterday=yesterday, low_stock_count=7)
    result.scalars.return_value.all.return_value = []
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    return db


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={'literal_binds': True}))


@pytest.mark.asyncio
@pytest.mark.parametrize('factory', ['东莞', '湖北', ''])
async def test_daily_aggregates_are_factory_scoped(factory):
    db = _db()
    scope = DashboardReadScope(factory=factory, orders=True, stockin=True, stockout=True)
    result = await stats._query_today_yesterday_base(db, DT, DT, DT, scope)

    assert result == (5, 3, 5, 3, 5, 3)
    for call in db.execute.await_args_list:
        sql = _sql(call.args[0])
        if factory:
            assert f"product.factory = '{factory}'" in sql
        else:
            assert 'product.factory' not in sql
    if factory:
        # 工厂谓词必须作用于正在汇总的同一 SKU，而非仅检查整单是否包含本厂 SKU。
        order_sql = _sql(db.execute.await_args_list[0].args[0])
        assert 'JOIN product ON product.id = order_item.product_id' in order_sql
        assert 'sum(order_item.quantity)' in order_sql
        assert 'EXISTS' not in order_sql


@pytest.mark.asyncio
@pytest.mark.parametrize('factory', ['', '东莞'])
async def test_restricted_module_stats_do_not_read_global_mv_or_other_modules(factory):
    db = _db()
    scope = DashboardReadScope(factory=factory, stockin=True)
    result = await stats.fetch_dashboard_stats(db, scope)

    assert (result['order_yesterday'], result['stockin_yesterday'], result['stockout_yesterday']) == (0, 3, 0)
    db.execute.assert_awaited_once()
    assert 'stock_in' in _sql(db.execute.await_args.args[0])


@pytest.mark.asyncio
async def test_all_readable_modules_in_bound_factory_still_skip_global_mv():
    db = _db()
    scope = DashboardReadScope(factory='东莞', orders=True, stockin=True, stockout=True)
    await stats.fetch_dashboard_stats(db, scope)
    assert db.execute.await_count == 3
    assert all('to_regclass(' not in _sql(call.args[0]) for call in db.execute.await_args_list)


@pytest.mark.asyncio
async def test_all_readable_modules_in_global_scope_can_use_existing_mv():
    db = _db()
    for field in ('mv_order', 'mv_stockin', 'mv_stockout'):
        setattr(db.execute.return_value.one.return_value, field, True)
    db.execute.return_value.__iter__.return_value = iter([
        SimpleNamespace(type='order', total_quantity=17),
        SimpleNamespace(type='stockin', total_quantity=19),
        SimpleNamespace(type='stockout', total_quantity=23),
    ])
    scope = DashboardReadScope(orders=True, stockin=True, stockout=True)
    result = await stats.fetch_dashboard_stats(db, scope)
    assert (result['order_yesterday'], result['stockin_yesterday'], result['stockout_yesterday']) == (17, 19, 23)
    assert 'to_regclass(' in _sql(db.execute.await_args_list[0].args[0])
    assert 'UNION ALL' in _sql(db.execute.await_args_list[-1].args[0])


@pytest.mark.asyncio
async def test_stats_inventory_cold_and_warm_by_factory(monkeypatch):
    dg, hb = _db(), _db()
    hb.execute.return_value.one.return_value.low_stock_count = 12
    sessions = iter((dg, hb))

    @asynccontextmanager
    async def fake_session():
        yield next(sessions)

    monkeypatch.setattr(database, 'get_async_db_context', fake_session)
    dg_scope = DashboardReadScope(factory='东莞', inventory=True)
    hb_scope = DashboardReadScope(factory='湖北', inventory=True)
    db = _db()
    for scope, expected in ((dg_scope, 7), (hb_scope, 12), (dg_scope, 7), (hb_scope, 12)):
        result = await stats.fetch_dashboard_stats(db, scope)
        assert result['low_stock_count'] == expected
        assert result['pending_approvals'] == 0
    db.execute.assert_not_awaited()
    for session, factory in ((dg, '东莞'), (hb, '湖北')):
        session.execute.assert_awaited_once()
        sql = _sql(session.execute.await_args.args[0])
        assert f"product.factory = '{factory}'" in sql
        assert 'approval_request' not in sql


@pytest.mark.asyncio
async def test_todos_filter_orders_and_do_not_query_unattributed_plans():
    db = _db()
    result = await todos.fetch_dashboard_todos(db, DashboardReadScope(factory='东莞', orders=True, plans=True))
    assert result == {'success': True, 'data': []}
    db.execute.assert_awaited_once()
    assert "product.factory = '东莞'" in _sql(db.execute.await_args.args[0])


@pytest.mark.asyncio
async def test_todos_plan_read_keeps_global_plan_available_for_authorized_scope():
    db = _db()
    await todos.fetch_dashboard_todos(db, DashboardReadScope(plans=True))
    db.execute.assert_awaited_once()
    assert 'production_plan' in _sql(db.execute.await_args.args[0])


@pytest.mark.asyncio
async def test_activities_partition_by_factory_and_source_with_warm_hits(monkeypatch):
    cache = {}
    monkeypatch.setattr(redis_wrapper, 'safe_get', AsyncMock(side_effect=lambda key, **_: cache.get(key)))
    monkeypatch.setattr(redis_wrapper, 'safe_set', AsyncMock(side_effect=lambda key, value, **_: cache.update({key: value})))
    for factory, source, expected_sql in (('东莞', 'stockin', 'stock_in'), ('湖北', 'stockin', 'stock_in'), ('东莞', 'stockout', 'stock_out')):
        scope = DashboardReadScope(factory=factory, **{source: True})
        db = _db()
        record_no = f'{factory}-{source}-01'
        row = SimpleNamespace(**{f'{source}_date': DT, f'{source}_no': record_no})
        db.execute.return_value.scalars.return_value.all.return_value = [row]
        cold = await activities.fetch_dashboard_activities(db, scope)
        assert [(item.type, item.title.split()[-1]) for item in cold] == [(source, record_no)]
        assert await activities.fetch_dashboard_activities(db, scope) == cold
        db.execute.assert_awaited_once()
        sql = _sql(db.execute.await_args.args[0])
        assert expected_sql in sql
        assert f"product.factory = '{factory}'" in sql
    assert len(cache) == 3
