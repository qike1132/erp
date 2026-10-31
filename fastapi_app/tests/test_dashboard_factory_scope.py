"""仪表盘工厂隔离与缓存分桶回归（2026-10-30 审计 A-M22）。

两个问题叠加：
1. `fetch_dashboard_stats` / `fetch_dashboard_todos` 的 `key_builder` 恒返回
   "global"：超管先请求写入全厂数字后，厂绑定用户在 30s 内读到的就是两厂合计。
2. 统计 SQL 本身没有工厂条件：即便缓存分桶，本厂用户拿到的仍是全厂口径。

修复：两端点按 `_dashboard_factory_scope(user)` 传 factory；缓存键带工厂；
日聚合（订单/入库/出库）与低库存数按 `Product.factory` 收窄；厂绑定用户
**不再走全厂物化视图**（MV 无工厂维度，覆盖会串厂）。
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from fastapi_app.services.dashboard import stats as stats_mod
from fastapi_app.services.dashboard import todos as todos_mod


def _row(**kwargs):
    r = MagicMock()
    for k, v in kwargs.items():
        setattr(r, k, v)
    return r


def _db_for_base():
    """三次聚合各返回 (today, yesterday) 行。"""
    rows = [
        _row(today=5, yesterday=3),
        _row(today=7, yesterday=2),
        _row(today=9, yesterday=4),
    ]
    result = MagicMock()
    result.one.side_effect = rows
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    return db


def _sql(stmt) -> str:
    return str(stmt.compile(compile_kwargs={'literal_binds': True}))


@pytest.mark.asyncio
async def test_daily_aggregates_are_factory_scoped():
    db = _db_for_base()

    await stats_mod._query_today_yesterday_base(
        db, MagicMock(), MagicMock(), MagicMock(), factory='东莞',
    )

    assert db.execute.await_count == 3
    for call in db.execute.await_args_list:
        sql = _sql(call.args[0])
        assert 'product.factory' in sql
        assert '东莞' in sql


@pytest.mark.asyncio
async def test_daily_aggregates_unscoped_when_factory_empty():
    db = _db_for_base()

    await stats_mod._query_today_yesterday_base(
        db, MagicMock(), MagicMock(), MagicMock(), factory='',
    )

    for call in db.execute.await_args_list:
        assert 'product.factory' not in _sql(call.args[0])


@pytest.mark.asyncio
async def test_scoped_stats_skip_materialized_views():
    """厂绑定用户不得用全厂 MV 覆盖本厂昨日值（会串厂）。"""
    results = []
    for today, yesterday in ((5, 3), (7, 2), (9, 4)):
        r = MagicMock()
        r.one.return_value = _row(today=today, yesterday=yesterday)
        results.append(r)
    db = MagicMock()
    db.execute = AsyncMock(side_effect=results)

    order_today, _oy, _st, _sy, _so, _soy, mv_flags = (
        await stats_mod._query_today_yesterday_base_with_mv(
            db, MagicMock(), MagicMock(), MagicMock(), MagicMock(), factory='东莞',
        )
    )

    assert mv_flags == (False, False, False)
    assert order_today == 5
    # 只跑了 3 条聚合，没有 to_regclass 的 MV 存在性检查
    assert db.execute.await_count == 3


class _StopError(Exception):
    """在取到缓存键后中断，避免真正跑查询。"""


@pytest.mark.asyncio
async def test_stats_cache_key_is_partitioned_by_factory(monkeypatch):
    from fastapi_app.core import cache as cache_mod

    keys: list[str] = []

    def _fake_build(prefix, key_builder, sig, args, kwargs):
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()
        key = f"{prefix}:{key_builder(**bound.arguments)}"
        keys.append(key)
        raise _StopError

    monkeypatch.setattr(cache_mod, '_build_cache_key', _fake_build)

    for factory in ('', '东莞', '湖北'):
        with pytest.raises(_StopError):
            await stats_mod.fetch_dashboard_stats(MagicMock(), factory)

    assert keys[0].endswith(':global')
    assert keys[1].endswith(':东莞')
    assert keys[2].endswith(':湖北')
    assert len(set(keys)) == 3


@pytest.mark.asyncio
async def test_todos_cache_key_is_partitioned_by_factory(monkeypatch):
    from fastapi_app.core import cache as cache_mod

    keys: list[str] = []

    def _fake_build(prefix, key_builder, sig, args, kwargs):
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()
        keys.append(f"{prefix}:{key_builder(**bound.arguments)}")
        raise _StopError

    monkeypatch.setattr(cache_mod, '_build_cache_key', _fake_build)

    for factory in ('', '东莞'):
        with pytest.raises(_StopError):
            await todos_mod.fetch_dashboard_todos(MagicMock(), factory)

    assert keys[0].endswith(':global')
    assert keys[1].endswith(':东莞')


@pytest.mark.asyncio
async def test_todos_filter_pending_orders_by_factory():
    empty = MagicMock()
    empty.scalars.return_value.all.return_value = []
    db = MagicMock()
    db.execute = AsyncMock(return_value=empty)

    await todos_mod.fetch_dashboard_todos(db, '东莞')

    first_sql = _sql(db.execute.await_args_list[0].args[0])
    assert 'product.factory' in first_sql
    assert '东莞' in first_sql


@pytest.mark.asyncio
async def test_todos_unscoped_keeps_all_pending_orders():
    empty = MagicMock()
    empty.scalars.return_value.all.return_value = []
    db = MagicMock()
    db.execute = AsyncMock(return_value=empty)

    await todos_mod.fetch_dashboard_todos(db, '')

    assert 'product.factory' not in _sql(db.execute.await_args_list[0].args[0])
