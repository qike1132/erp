"""
数据查询 / 报表统计 单元测试

覆盖：
- SQL 标识符安全校验（白名单）
- 聚合函数安全校验（PostgreSQL STRING_AGG，白名单表达式/分隔符）
- 通用日志查询 _query_logs_generic（分页 + COUNT(*) OVER() 合并计数）
- 订单流水 / 备货流水 / 出货流水 / 抵扣流水 的筛选条件构建与严格日期解析
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.core.cache import _cache_local
from fastapi_app.services.report_service import (
    _query_logs_generic,
    _quote_identifier,
    _string_agg,
    get_deduction_logs,
    get_order_logs,
    get_return_logs,
    get_stockin_logs,
    get_stockout_logs,
)


@pytest.fixture(autouse=True)
def _no_redis_cache():
    """隔离缓存：禁用 Redis（L2），清空进程内 L1"""
    _cache_local.clear()
    with patch('fastapi_app.core.cache._get_redis_cache', return_value=None):
        yield
    _cache_local.clear()


class TestSQLHelpers:
    """SQL 安全辅助函数"""

    def test_quote_identifier_valid(self):
        """合法标识符（仅支持 PostgreSQL 双引号）"""
        result = _quote_identifier('order')
        assert result == '"order"'

    def test_quote_identifier_invalid(self):
        """非法标识符"""
        with pytest.raises(ValueError, match='非法SQL标识符'):
            _quote_identifier('users_table')  # 不在白名单中

    def test_string_agg_valid_expr(self):
        """合法聚合表达式（仅支持 PostgreSQL STRING_AGG）"""
        result = _string_agg('o.order_no', ', ')
        assert 'STRING_AGG' in result
        assert 'o.order_no' in result
        assert 'DISTINCT' in result

    def test_string_agg_no_distinct(self):
        """关闭 DISTINCT"""
        result = _string_agg('o.order_no', ', ', distinct=False)
        assert 'DISTINCT' not in result

    def test_string_agg_invalid_expr(self):
        """非法表达式"""
        with pytest.raises(ValueError, match='非法SQL聚合表达式'):
            _string_agg('o.password', ', ')

    def test_string_agg_invalid_separator(self):
        """非法分隔符"""
        with pytest.raises(ValueError, match='非法SQL聚合分隔符'):
            _string_agg('o.order_no', '--')


class TestQueryLogsGeneric:
    """通用日志查询"""

    @pytest.mark.asyncio
    async def test_empty_result(self, mock_async_db):
        """空结果集"""
        exec_result = MagicMock()
        exec_result.fetchall.return_value = []
        exec_result.scalar.return_value = 0
        mock_async_db.execute = AsyncMock(return_value=exec_result)

        result = await _query_logs_generic(
            mock_async_db,
            base_where=[],
            data_sql_template='SELECT 1 {where_sql}',
            qty_sql_template='SELECT 0 {where_sql}',
            params={},
            page=1,
            per_page=20,
            row_mapper=lambda r: {},
        )

        assert result['success'] is True
        assert result['logs'] == []
        assert result['stats']['total_count'] == 0
        assert result['stats']['total_quantity'] == 0
        assert result['pagination']['pages'] == 0

    @pytest.mark.asyncio
    async def test_where_clause_join(self, mock_async_db):
        """多个 where 条件以 AND 拼接"""
        exec_result = MagicMock()
        exec_result.fetchall.return_value = []
        exec_result.scalar.return_value = 0
        mock_async_db.execute = AsyncMock(return_value=exec_result)

        await _query_logs_generic(
            mock_async_db,
            base_where=['a = :a', 'b = :b'],
            data_sql_template='SELECT 1 {where_sql}',
            qty_sql_template='SELECT 0 {where_sql}',
            params={'a': 1, 'b': 2},
            page=1,
            per_page=20,
            row_mapper=lambda r: {},
        )

        executed_sql = mock_async_db.execute.call_args_list[0][0][0].text
        assert 'a = :a AND b = :b' in executed_sql


def _patch_generic(return_value=None):
    """patch _query_logs_generic，仅验证调用参数"""
    return patch(
        'fastapi_app.services.report_service._query_logs_generic',
        new=AsyncMock(return_value=return_value or {'success': True, 'logs': []}),
    )


class TestGetOrderLogs:
    """订单流水"""

    @pytest.mark.asyncio
    async def test_filters_build_where(self, mock_async_db):
        """客户/产品/状态筛选进入 where 条件"""
        with _patch_generic() as m:
            await get_order_logs(
                mock_async_db, customer='测试客户', product='产品A',
                status='已备货', page=1, per_page=20,
            )
        where = m.call_args.kwargs['base_where']
        assert any('o.customer LIKE' in c for c in where)
        assert any('p.name LIKE' in c for c in where)
        assert any('o.status = :status' in c for c in where)

    @pytest.mark.asyncio
    async def test_invalid_status_ignored(self, mock_async_db):
        """非法状态值被忽略（不进 where）"""
        with _patch_generic() as m:
            await get_order_logs(mock_async_db, status='非法状态')
        where = m.call_args.kwargs['base_where']
        assert not any('o.status' in c for c in where)

    @pytest.mark.asyncio
    async def test_per_page_clamped(self, mock_async_db):
        """per_page 上限 100"""
        with _patch_generic() as m:
            await get_order_logs(mock_async_db, per_page=5000)
        assert m.call_args.kwargs['per_page'] == 100

    @pytest.mark.asyncio
    async def test_invalid_date_raises(self, mock_async_db):
        """非法日期格式抛 ValueError（不再静默忽略）"""
        with _patch_generic():
            with pytest.raises(ValueError):
                await get_order_logs(mock_async_db, start_date='2024/01/01')


class TestGetStockinLogs:
    """备货流水"""

    @pytest.mark.asyncio
    async def test_filters_build_where(self, mock_async_db):
        with _patch_generic() as m:
            await get_stockin_logs(
                mock_async_db, customer='客户X',
                start_date='2024-01-01', end_date='2024-01-31',
            )
        where = m.call_args.kwargs['base_where']
        assert any('s.stockin_date >= :start_date' in c for c in where)
        assert any('s.stockin_date < :end_date' in c for c in where)
        params = m.call_args.kwargs['params']
        assert params['customer'] == '%客户X%'


class TestGetStockoutLogs:
    """出货流水"""

    @pytest.mark.asyncio
    async def test_base_where_invariants(self, mock_async_db):
        """固定条件：净出货量为正 + 非抵扣 + 关联订单未删除"""
        with _patch_generic() as m:
            await get_stockout_logs(mock_async_db)
        where = m.call_args.kwargs['base_where']
        assert '(so.quantity - so.returned_quantity) > 0' in where
        assert 'so.stockin_id IS NULL' in where


class TestGetDeductionLogs:
    """备货抵扣流水"""

    @pytest.mark.asyncio
    async def test_base_where_invariants(self, mock_async_db):
        """固定条件：stockin_id 非空（抵扣出货）"""
        with _patch_generic() as m:
            await get_deduction_logs(mock_async_db, customer='客户Y')
        where = m.call_args.kwargs['base_where']
        assert 'so.stockin_id IS NOT NULL' in where


class TestGetReturnLogs:
    """退货流水"""

    @pytest.mark.asyncio
    async def test_base_where_invariants(self, mock_async_db):
        """固定条件：仅统计 active（cancelled 已对称扣回，不计入流水）"""
        with _patch_generic() as m:
            await get_return_logs(mock_async_db)
        where = m.call_args.kwargs['base_where']
        assert "sr.status = 'active'" in where

    @pytest.mark.asyncio
    async def test_filters_build_where(self, mock_async_db):
        """客户/产品/日期筛选进入 where 条件"""
        with _patch_generic() as m:
            await get_return_logs(
                mock_async_db, customer='客户Z', product='产品B',
                start_date='2026-10-01', end_date='2026-10-31',
            )
        where = m.call_args.kwargs['base_where']
        assert any("COALESCE(sr.customer, '') LIKE :customer" in c for c in where)
        assert any("COALESCE(p.name, '') LIKE :product" in c for c in where)
        assert any('sr.return_date >= :start_date' in c for c in where)
        assert any('sr.return_date < :end_date' in c for c in where)
        params = m.call_args.kwargs['params']
        assert params['customer'] == '%客户Z%'

    @pytest.mark.asyncio
    async def test_per_page_clamped(self, mock_async_db):
        """per_page 上限 100"""
        with _patch_generic() as m:
            await get_return_logs(mock_async_db, per_page=5000)
        assert m.call_args.kwargs['per_page'] == 100

    @pytest.mark.asyncio
    async def test_invalid_date_raises(self, mock_async_db):
        """非法日期格式抛 ValueError（与其他流水一致）"""
        with _patch_generic():
            with pytest.raises(ValueError):
                await get_return_logs(mock_async_db, start_date='2026/10/01')


class TestExportTypeParity:
    """导出类型口径一致性守卫

    新增报表类型需四处同步：/reports/export 的 ALLOWED_REPORT_TYPES、
    /tasks/export-report 的 ASYNC_EXPORT_REPORT_TYPES、ARQ worker 的
    _EXPORT_METHODS、report_data_service.get_all_logs_data 的分支。
    本类钉住前三处集合一致且方法表可解析（分支遗漏会在冒烟测试暴露）。
    """

    def test_type_sets_identical(self):
        from fastapi_app.api.v1.endpoints.report import ALLOWED_REPORT_TYPES
        from fastapi_app.api.v1.endpoints.tasks import ASYNC_EXPORT_REPORT_TYPES
        from fastapi_app.tasks.report_tasks import _EXPORT_METHODS

        assert set(ALLOWED_REPORT_TYPES) == set(ASYNC_EXPORT_REPORT_TYPES) == set(_EXPORT_METHODS)

    def test_worker_methods_resolve(self):
        from fastapi_app.tasks.report_tasks import _EXPORT_METHODS
        from utils.report_exporter import ReportExporter

        for attr in _EXPORT_METHODS.values():
            assert callable(getattr(ReportExporter, attr)), attr
