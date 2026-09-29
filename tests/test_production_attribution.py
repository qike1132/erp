"""生产量摊派的纯函数单元测试

覆盖（均无数据库依赖）：
    - aggregate_produced_by_product: 生产记录行 → {product_id: 累计量}
    - group_details_by_product: 计划明细按 product_id 分组
    - production_window: 取数窗口（含跨年边界）
    - allocate_fifo 以产品为键的摊派行为

导入方式说明：三个**本任务新建**的函数走模块限定名（`fifo.xxx`），
不写进顶部 import。否则在它们被创建之前，每次中间运行都会先 ImportError，
逐步的 RED→GREEN 证据链就断了。
"""
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.services import fifo_allocation as fifo
from fastapi_app.services import purchase_plan_shipment as pps
from fastapi_app.services.fifo_allocation import allocate_fifo
from fastapi_app.shared_models import DailyProductionRecord, StockOut


def _dispatch_execute(details_rows, prod_rows):
    """按语句类型分派 mock 的 db.execute 返回，使断言不依赖「查询先后顺序」。

    生产量分配里会有三类 execute：SET LOCAL / RESET 超时、取计划明细、聚合生产量。
    若用 side_effect 列表，一旦实现新增或调整查询顺序，测试就会以「mock 错位」
    的假失败告终；按语句内容分派则对顺序免疫。
    """
    async def _ex(stmt, *args, **kwargs):
        sql = str(stmt)
        if 'daily_production_record' in sql:
            res = MagicMock()
            res.all.return_value = prod_rows
            return res
        if 'purchase_plan_details' in sql:
            res = MagicMock()
            res.scalars.return_value.all.return_value = details_rows
            return res
        return MagicMock()  # SET LOCAL / RESET statement_timeout
    return _ex


def _make_detail(detail_id: int, quantity: int, plan_date=None, product_id: int = 1, plan_id: int = 1):
    """创建 mock PurchasePlanDetail"""
    d = MagicMock()
    d.id = detail_id
    d.plan_id = plan_id
    d.quantity = quantity
    d.product_name = f'P{product_id}'
    d.plan_date = plan_date
    d.product_id = product_id
    return d


def _make_prod_row(product_id, quantity):
    """创建 mock DailyProductionRecord 行"""
    r = MagicMock()
    r.product_id = product_id
    r.quantity = quantity
    return r


class TestAggregateProducedByProduct:
    def test_sums_same_product(self):
        rows = [_make_prod_row(1, 100), _make_prod_row(1, 50), _make_prod_row(2, 30)]
        assert fifo.aggregate_produced_by_product(rows) == {1: 150, 2: 30}

    def test_drops_rows_without_product_id(self):
        """product_id 为空的历史脏数据必须丢弃，不得算进任何产品"""
        rows = [_make_prod_row(None, 999), _make_prod_row(1, 100)]
        assert fifo.aggregate_produced_by_product(rows) == {1: 100}

    def test_treats_none_quantity_as_zero(self):
        """quantity 为 NULL 的行按 0 计，不得让 None 参与加法报错"""
        rows = [_make_prod_row(1, None), _make_prod_row(1, 70)]
        assert fifo.aggregate_produced_by_product(rows) == {1: 70}

    def test_no_rows(self):
        assert fifo.aggregate_produced_by_product([]) == {}


class TestAllocateFifoByProduct:
    def test_fills_earliest_plan_first(self):
        """同一产品的计划按 plan_date 先后被生产量填满"""
        d1 = _make_detail(1, 10, plan_date=date(2026, 9, 20), product_id=7)
        d2 = _make_detail(2, 20, plan_date=date(2026, 9, 5), product_id=7)
        details_by_key = {7: [d2, d1]}          # 调用方保证已按 plan_date ASC 排序
        total_by_key = {7: 15}
        result = allocate_fifo([d1, d2], details_by_key, total_by_key)
        assert result[2] == 15   # 早的那条（9/05）被填
        assert result[1] == 0    # 晚的那条（9/20）没被填

    def test_allocated_never_exceeds_plan(self):
        """生产量远超计划量时，每行分配值钳在 quantity 以内，溢出丢弃"""
        d1 = _make_detail(1, 100, plan_date=date(2026, 9, 1), product_id=7)
        d2 = _make_detail(2, 50, plan_date=date(2026, 9, 2), product_id=7)
        details_by_key = {7: [d1, d2]}
        total_by_key = {7: 9999}
        result = allocate_fifo([d1, d2], details_by_key, total_by_key)
        assert result == {1: 100, 2: 50}

    def test_same_plan_date_is_stable(self):
        """plan_date 相同时按传入顺序分配，结果可复现（不随 set/dict 顺序漂移）"""
        d1 = _make_detail(1, 10, plan_date=date(2026, 9, 1), plan_id=1, product_id=7)
        d2 = _make_detail(2, 10, plan_date=date(2026, 9, 1), plan_id=2, product_id=7)
        details_by_key = {7: [d1, d2]}
        total_by_key = {7: 10}
        first = allocate_fifo([d1, d2], details_by_key, total_by_key)
        second = allocate_fifo([d1, d2], details_by_key, total_by_key)
        assert first == second
        assert first == {1: 10, 2: 0}

    def test_different_products_do_not_cross(self):
        """不同产品的产量互不串门"""
        d1 = _make_detail(1, 10, plan_date=date(2026, 9, 1), product_id=7)
        d2 = _make_detail(2, 10, plan_date=date(2026, 9, 1), product_id=8)
        details_by_key = {7: [d1], 8: [d2]}
        total_by_key = {7: 10}
        result = allocate_fifo([d1, d2], details_by_key, total_by_key)
        assert result == {1: 10, 2: 0}


class TestGroupDetailsByProduct:
    def test_groups_and_preserves_order(self):
        d1 = _make_detail(1, 10, plan_date=date(2026, 9, 1), product_id=7)
        d2 = _make_detail(2, 10, plan_date=date(2026, 9, 2), product_id=7)
        d3 = _make_detail(3, 10, plan_date=date(2026, 9, 3), product_id=8)
        grouped = fifo.group_details_by_product([d1, d2, d3])
        assert list(grouped.keys()) == [7, 8]
        assert [d.id for d in grouped[7]] == [1, 2]

    def test_drops_details_without_product_id(self):
        d1 = _make_detail(1, 10, product_id=0)     # product_id=0 视为空
        d2 = _make_detail(2, 10, product_id=7)
        grouped = fifo.group_details_by_product([d1, d2])
        assert grouped == {7: [d2]}

    def test_empty(self):
        assert fifo.group_details_by_product([]) == {}


class TestProductionWindow:
    def test_normal_month(self):
        """计划月 2026-09 → 起点 2026-08-01，终点为「今天」"""
        start, end = fifo.production_window('2026-09', datetime(2026, 9, 29, 10, 30))
        assert start == date(2026, 8, 1)
        assert end == date(2026, 9, 29)

    def test_year_boundary(self):
        """计划月 2026-01 → 起点落在上一年 12 月"""
        start, end = fifo.production_window('2026-01', datetime(2026, 1, 5, 0, 0))
        assert start == date(2025, 12, 1)
        assert end == date(2026, 1, 5)

    def test_end_is_today_not_month_end(self):
        """上界是「现在」而非计划月末：历史月份的数字应随后续生产继续上升"""
        start, end = fifo.production_window('2026-03', datetime(2026, 9, 29, 23, 59))
        assert end == date(2026, 9, 29)
        assert start == date(2026, 2, 1)


class TestGetProducedFifoMap:
    """_get_produced_fifo_map 的查询与缓存行为（DB 与 Redis 均 mock）"""

    @pytest.mark.asyncio
    async def test_no_production_records_yields_zero_allocation(self):
        """窗口内完全没有生产记录 → 每行分配 0（前端显示全部待生产），且不抛异常"""
        d1 = _make_detail(1, 100, plan_date=date(2026, 9, 8), product_id=7)
        db = AsyncMock()
        # 生产量分配会做两类查询（取该月该产品明细、聚合生产量），按语句分派 mock 才不依赖
        # 查询顺序；生产量命中 0 行即「窗口内没有生产记录」这个场景。
        db.execute.side_effect = _dispatch_execute([d1], [])

        with patch.object(fifo, 'safe_get', AsyncMock(return_value=None)), \
             patch.object(fifo, 'safe_set', AsyncMock()):
            result = await fifo._get_produced_fifo_map(db, [d1], plan_month='2026-09')

        assert result == {1: 0}

    @pytest.mark.asyncio
    async def test_allocates_by_product_in_plan_date_order(self):
        """生产量按 plan_date 先后摊到该产品的计划行上（跨客户也不分组）"""
        early = _make_detail(1, 100, plan_date=date(2026, 9, 5), product_id=7, plan_id=1)
        late = _make_detail(2, 100, plan_date=date(2026, 9, 20), product_id=7, plan_id=2)
        db = AsyncMock()
        db.execute.side_effect = _dispatch_execute([early, late], [_make_prod_row(7, 150)])

        with patch.object(fifo, 'safe_get', AsyncMock(return_value=None)), \
             patch.object(fifo, 'safe_set', AsyncMock()):
            result = await fifo._get_produced_fifo_map(db, [early, late], plan_month='2026-09')

        assert result == {1: 100, 2: 50}

    @pytest.mark.asyncio
    async def test_empty_details_short_circuits(self):
        db = AsyncMock()
        with patch.object(fifo, 'safe_get', AsyncMock(return_value=None)), \
             patch.object(fifo, 'safe_set', AsyncMock()):
            assert await fifo._get_produced_fifo_map(db, [], plan_month='2026-09') == {}
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_hit_skips_query(self):
        """缓存覆盖了全部需查询的明细 id 时直接返回，不再打 DB"""
        d1 = _make_detail(1, 100, plan_date=date(2026, 9, 8), product_id=7)
        db = AsyncMock()
        with patch.object(fifo, 'safe_get', AsyncMock(return_value={'1': 42})), \
             patch.object(fifo, 'safe_set', AsyncMock()):
            result = await fifo._get_produced_fifo_map(db, [d1], plan_month='2026-09')
        assert result == {1: 42}
        db.execute.assert_not_called()


class TestProductionCacheInvalidation:
    def test_production_record_write_marks_session_dirty(self):
        """DailyProductionRecord 的增删改必须置脏标记，否则会话提交后不清缓存"""
        record = MagicMock(spec=DailyProductionRecord)
        session = MagicMock()
        session.info = {}
        session.new = [record]
        session.dirty = []
        session.deleted = []
        fifo._fifo_before_commit(session)
        assert session.info.get('fifo_dirty') is True

    def test_unrelated_write_does_not_mark_dirty(self):
        """无关模型的写入不应触发清缓存（避免每次都白清）"""
        session = MagicMock()
        session.info = {}
        session.new = [object()]
        session.dirty = []
        session.deleted = []
        fifo._fifo_before_commit(session)
        assert session.info.get('fifo_dirty') is None


class TestProducedFifoMapSafe:
    @pytest.mark.asyncio
    async def test_query_failure_degrades_with_flag(self):
        """查询不可用时返回空映射 + degraded=True，不得返回全 0 冒充「没生产」"""
        db = AsyncMock()
        # 注意 patch 的目标是**消费方** purchase_plan_shipment 里的名字：
        # 该模块用 `from ... import _get_produced_fifo_map` 绑定了自己的引用，
        # patch 源模块 fifo_allocation 上的同名属性对它无效（经典 patch 打错地方）。
        with patch.object(pps, '_get_produced_fifo_map',
                          AsyncMock(side_effect=RuntimeError('FIFO_ALLOCATION_UNAVAILABLE'))):
            result, degraded = await pps._get_produced_fifo_map_safe(db, [_make_detail(1, 10, product_id=7)])
        assert result == {}
        assert degraded is True

    @pytest.mark.asyncio
    async def test_success_passes_through(self):
        db = AsyncMock()
        with patch.object(pps, '_get_produced_fifo_map', AsyncMock(return_value={1: 42})):
            result, degraded = await pps._get_produced_fifo_map_safe(db, [_make_detail(1, 10, product_id=7)])
        assert result == {1: 42}
        assert degraded is False


class TestProducedAllocationScope:
    """摊派范围必须与调用方传进来的子集无关（评审 I2）。

    get_day_details 只传当天的明细；若就着这个子集摊派，当天的行会独吞
    整个窗口的产量，同一个计划行在月历上与在弹窗里会给出不同的数字。
    """

    @pytest.mark.asyncio
    async def test_subset_view_gets_date_ordered_share(self):
        earlier = _make_detail(1, 100, plan_date=date(2026, 9, 5), product_id=7, plan_id=1)
        today = _make_detail(2, 100, plan_date=date(2026, 9, 20), product_id=7, plan_id=2)
        db = AsyncMock()
        db.execute.side_effect = _dispatch_execute([earlier, today], [_make_prod_row(7, 150)])
        set_mock = AsyncMock()

        with patch.object(fifo, 'safe_get', AsyncMock(return_value=None)), \
             patch.object(fifo, 'safe_set', set_mock):
            # 只传当天那一条明细
            result = await fifo._get_produced_fifo_map(db, [today], plan_month='2026-09')

        # 150 先填满更早的 9/05，剩下 50 才轮到 9/20 —— 不是让 9/20 独吞 150 或被钳成 100
        assert result == {2: 50}

    @pytest.mark.asyncio
    async def test_cache_stores_month_wide_map(self):
        """缓存按「月份级存全体」——否则别的子集视图命中后拿到的是残缺映射"""
        earlier = _make_detail(1, 100, plan_date=date(2026, 9, 5), product_id=7, plan_id=1)
        today = _make_detail(2, 100, plan_date=date(2026, 9, 20), product_id=7, plan_id=2)
        db = AsyncMock()
        db.execute.side_effect = _dispatch_execute([earlier, today], [_make_prod_row(7, 150)])
        set_mock = AsyncMock()

        with patch.object(fifo, 'safe_get', AsyncMock(return_value=None)), \
             patch.object(fifo, 'safe_set', set_mock):
            await fifo._get_produced_fifo_map(db, [today], plan_month='2026-09')

        cached = set_mock.call_args[0][1]
        assert cached == {'1': 100, '2': 50}


class TestProductionAggregateCacheInvalidation:
    """生产记录写入必须同时清「聚合响应缓存」（评审 I1）。

    页面读的是聚合缓存（pp:agg TTL 120s / 本地 30s），而聚合里的 produced_* 来自
    生产量。只清分配缓存的话，录入生产记录后刷新页面最长两分钟看不到变化 ——
    计划的人工验收步骤（录入→刷新应变）会因此假失败。
    """

    def test_production_record_write_marks_produced_dirty(self):
        record = MagicMock(spec=DailyProductionRecord)
        session = MagicMock()
        session.info = {}
        session.new = [record]
        session.dirty = []
        session.deleted = []
        fifo._fifo_before_commit(session)
        assert session.info.get('fifo_dirty') is True
        assert session.info.get('produced_dirty') is True

    def test_stockout_write_does_not_mark_produced_dirty(self):
        """纯出货写入不置生产标记 —— 那条路径的 pp 失效由 shipment recalc 负责"""
        record = MagicMock(spec=StockOut)
        session = MagicMock()
        session.info = {}
        session.new = [record]
        session.dirty = []
        session.deleted = []
        fifo._fifo_before_commit(session)
        assert session.info.get('fifo_dirty') is True
        assert session.info.get('produced_dirty') is None

    @pytest.mark.asyncio
    async def test_produced_dirty_clears_plan_aggregate_caches(self):
        patterns: list[str] = []

        async def _inv(_strategy, pats):
            patterns.extend(pats)

        mgr = MagicMock()
        mgr.invalidate = AsyncMock(side_effect=_inv)
        with patch.object(fifo, 'cache_mgr', mgr), \
             patch.object(fifo, 'invalidate_local_cache') as local:
            await fifo._invalidate_fifo_caches_safe(produced_dirty=True)
        local_pats = [c.args[0] for c in local.call_args_list]

        assert any(p.startswith('pp:') for p in patterns), patterns
        assert any(p.startswith('pp:') for p in local_pats), local_pats

    @pytest.mark.asyncio
    async def test_not_produced_dirty_leaves_plan_aggregate_caches_alone(self):
        patterns: list[str] = []

        async def _inv(_strategy, pats):
            patterns.extend(pats)

        mgr = MagicMock()
        mgr.invalidate = AsyncMock(side_effect=_inv)
        with patch.object(fifo, 'cache_mgr', mgr), \
             patch.object(fifo, 'invalidate_local_cache'):
            await fifo._invalidate_fifo_caches_safe(produced_dirty=False)

        assert not any(p.startswith('pp:') for p in patterns), patterns
