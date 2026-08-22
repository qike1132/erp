"""dashboard_service.py 中提取的 helper 函数 - 单元测试

覆盖 P1-1 重构提取的 helper：
- _query_today_yesterday_base（合并 today+yesterday 基表查询）
- _resolve_yesterday_from_mv（物化视图数据覆盖 yesterday 基表值）
- _query_production_stats（生产排产统计）
"""
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.services import dashboard_service


def _row(today=0, yesterday=0):
    """构造具名行 mock，支持 .today / .yesterday 属性访问"""
    r = MagicMock()
    r.today = today
    r.yesterday = yesterday
    return r


# ============================================================================
# _query_today_yesterday_base
# ============================================================================
class TestQueryTodayYesterdayBase:
    @pytest.mark.asyncio
    async def test_returns_six_tuple_from_three_queries(self):
        """应执行 3 次查询（Order/StockIn/StockOut）并返回 6 元组"""
        order_row = _row(today=10, yesterday=8)
        stockin_row = _row(today=20, yesterday=15)
        stockout_row = _row(today=5, yesterday=3)

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            MagicMock(one=MagicMock(return_value=order_row)),
            MagicMock(one=MagicMock(return_value=stockin_row)),
            MagicMock(one=MagicMock(return_value=stockout_row)),
        ])

        result = await dashboard_service._query_today_yesterday_base(
            db, datetime(2026, 1, 1), datetime(2026, 1, 2), datetime(2025, 12, 31),
        )
        assert result == (10, 8, 20, 15, 5, 3)
        assert db.execute.await_count == 3

    @pytest.mark.asyncio
    async def test_converts_zero_sums_to_zero_int(self):
        """SUM 为 0（coalesce 保证非 None）时应转为 int 0"""
        order_row = _row(today=0, yesterday=0)
        stockin_row = _row(today=0, yesterday=0)
        stockout_row = _row(today=0, yesterday=0)

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            MagicMock(one=MagicMock(return_value=order_row)),
            MagicMock(one=MagicMock(return_value=stockin_row)),
            MagicMock(one=MagicMock(return_value=stockout_row)),
        ])

        result = await dashboard_service._query_today_yesterday_base(
            db, datetime(2026, 1, 1), datetime(2026, 1, 2), datetime(2025, 12, 31),
        )
        assert result == (0, 0, 0, 0, 0, 0)
        # 所有值应为 int 类型
        assert all(isinstance(v, int) for v in result)


# ============================================================================
# _resolve_yesterday_from_mv
# ============================================================================
class TestResolveYesterdayFromMv:
    @pytest.mark.asyncio
    async def test_all_mvs_present_uses_union_all_query(self):
        """所有 MV 存在时应走 UNION ALL 单次查询路径"""
        mv_data = MagicMock()
        # 模拟 r.type / r.total_quantity 属性访问
        rows = [
            MagicMock(type='order', total_quantity=100),
            MagicMock(type='stockin', total_quantity=200),
            MagicMock(type='stockout', total_quantity=50),
        ]
        mv_data.__iter__ = MagicMock(return_value=iter(rows))

        db = AsyncMock()
        db.execute = AsyncMock(return_value=mv_data)

        result = await dashboard_service._resolve_yesterday_from_mv(
            db, mv_order_ok=True, mv_stockin_ok=True, mv_stockout_ok=True,
            yesterday_date=date(2026, 1, 1),
            order_yesterday_base=10, stockin_yesterday_base=20, stockout_yesterday_base=5,
        )
        assert result == (100, 200, 50)
        assert db.execute.await_count == 1

    @pytest.mark.asyncio
    async def test_partial_mvs_falls_back_to_individual_queries(self):
        """部分 MV 缺失时应逐个查询降级"""
        db = AsyncMock()
        # _mv_or_base 对缺失 MV 直接返回 base，对存在 MV 查询
        # 注:重构后 _mv_or_base 定义于 services/dashboard/stats 子模块,需 patch 其真实位置
        with patch('fastapi_app.services.dashboard.stats._mv_or_base', new=AsyncMock(side_effect=[100, 20, 5])):
            result = await dashboard_service._resolve_yesterday_from_mv(
                db, mv_order_ok=True, mv_stockin_ok=False, mv_stockout_ok=False,
                yesterday_date=date(2026, 1, 1),
                order_yesterday_base=10, stockin_yesterday_base=20, stockout_yesterday_base=5,
            )
        assert result == (100, 20, 5)

    @pytest.mark.asyncio
    async def test_mv_returns_none_falls_back_to_base(self):
        """MV 查询返回 None 时应使用 base 值"""
        mv_data = MagicMock()
        rows = [MagicMock(type='order', total_quantity=None)]
        mv_data.__iter__ = MagicMock(return_value=iter(rows))

        db = AsyncMock()
        db.execute = AsyncMock(return_value=mv_data)

        result = await dashboard_service._resolve_yesterday_from_mv(
            db, mv_order_ok=True, mv_stockin_ok=True, mv_stockout_ok=True,
            yesterday_date=date(2026, 1, 1),
            order_yesterday_base=99, stockin_yesterday_base=88, stockout_yesterday_base=77,
        )
        # order MV 为 None → 使用 base 99；stockin/stockout MV 缺失 → 使用 base
        assert result[0] == 99
        assert result[1] == 88
        assert result[2] == 77


# ============================================================================
# _query_production_stats
# ============================================================================
class TestQueryProductionStats:
    @pytest.mark.asyncio
    async def test_computes_completion_rate_and_pending_shipments(self):
        """应正确计算完工率与待出货数"""
        prod_stats = MagicMock()
        prod_stats.__getitem__ = MagicMock(side_effect=[10, 7])  # total=10, completed=7
        prod_stats.__iter__ = MagicMock(return_value=iter([10, 7]))

        result_mock = MagicMock()
        result_mock.one.return_value = prod_stats

        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        result = await dashboard_service._query_production_stats(db, datetime(2026, 1, 1))
        assert result['production_completion_rate'] == 0.7
        assert result['pending_shipments'] == 3

    @pytest.mark.asyncio
    async def test_zero_total_plans_yields_zero_rate(self):
        """总计划数为 0 时完工率应为 0.0，避免除零"""
        prod_stats = MagicMock()
        prod_stats.__getitem__ = MagicMock(side_effect=[0, 0])
        prod_stats.__iter__ = MagicMock(return_value=iter([0, 0]))

        result_mock = MagicMock()
        result_mock.one.return_value = prod_stats

        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        result = await dashboard_service._query_production_stats(db, datetime(2026, 1, 1))
        assert result['production_completion_rate'] == 0.0
        assert result['pending_shipments'] == 0

    @pytest.mark.asyncio
    async def test_exception_sets_safe_defaults(self):
        """查询异常时应设置安全默认值，不抛出"""
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=RuntimeError("db down"))

        # 不应抛异常
        result = await dashboard_service._query_production_stats(db, datetime(2026, 1, 1))
        assert result['production_completion_rate'] == 0.0
        assert result['pending_shipments'] == 0

    @pytest.mark.asyncio
    async def test_none_counts_treated_as_zero(self):
        """计数为 None 时应按 0 处理"""
        prod_stats = MagicMock()
        prod_stats.__getitem__ = MagicMock(side_effect=[None, None])
        prod_stats.__iter__ = MagicMock(return_value=iter([None, None]))

        result_mock = MagicMock()
        result_mock.one.return_value = prod_stats

        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        result = await dashboard_service._query_production_stats(db, datetime(2026, 1, 1))
        assert result['production_completion_rate'] == 0.0
        assert result['pending_shipments'] == 0
