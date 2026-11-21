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
        # ILIKE（大小写不敏感，审计 data-M-3）：与库存页 _resolve_products 同口径，
        # m01 必须搜得到 M01。
        assert any('o.customer ILIKE' in c for c in where)
        # 产品筛选与 SELECT 的显示口径同源（COALESCE(p.*, oi.*)）：多 SKU 展开后，
        # 产品行缺失的 SKU 行会显示 oi.product_name，筛选必须也能命中它。
        assert any('COALESCE(p.name, oi.product_name) ILIKE :product' in c for c in where)
        assert any('o.status = :status' in c for c in where)

    def test_export_filter_invalid_status_raises(self):
        """导出链路的非法状态必须抛 BusinessError（不能被 get_all_logs_data 吞成空结果）。

        若改回 ValueError，外层 `except (ValueError, TypeError, OSError)` 会把它吞掉，
        端点拿不到 400，只会导出一个空 Excel——与屏幕端 400 的行为分叉。
        """
        from sqlalchemy import select

        from fastapi_app.core.exceptions import BusinessError
        from fastapi_app.shared.report_data_service import _apply_order_filters
        from fastapi_app.shared_models import Order

        with pytest.raises(BusinessError):
            _apply_order_filters(select(Order), '', '', 'bogus', '', '', '')

    @pytest.mark.asyncio
    async def test_invalid_status_rejected(self, mock_async_db):
        """非法状态值必须报错，不能静默返回全量。

        原用例（test_invalid_status_ignored）锁定的正是缺陷行为：前端传了脏值
        （如移动端历史英文键）时接口 200 + 全量数据，用户以为筛选生效，
        导出给客户的流水会包含全部状态。改为与「非法日期必须报错」同口径。
        """
        from fastapi_app.core.exceptions import BusinessError

        with pytest.raises(BusinessError):
            await get_order_logs(mock_async_db, status='非法状态')

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
        """固定条件：出货毛量为正（不扣退货）+ 非抵扣 + 关联订单未删除"""
        with _patch_generic() as m:
            await get_stockout_logs(mock_async_db)
        where = m.call_args.kwargs['base_where']
        assert 'so.quantity > 0' in where
        assert 'so.stockin_id IS NULL' in where


class TestGetDeductionLogs:
    """备货抵扣流水"""

    @pytest.mark.asyncio
    async def test_base_where_invariants(self, mock_async_db):
        """固定条件：stockin_id 非空（抵扣出货）+ 净量>0（与导出口径对齐）"""
        with _patch_generic() as m:
            await get_deduction_logs(mock_async_db, customer='客户Y')
        where = m.call_args.kwargs['base_where']
        assert 'so.stockin_id IS NOT NULL' in where
        # 第八轮审计在导出侧补的「净量>0」必须同步在屏幕侧，全退抵扣不再以 0 数量计入
        assert '(so.quantity - so.returned_quantity) > 0' in where


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
        assert any("COALESCE(sr.customer, '') ILIKE :customer" in c for c in where)
        assert any("COALESCE(p.name, '') ILIKE :product" in c for c in where)
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
        from fastapi_app.shared.report_export import EXPORT_METHOD_NAMES, REPORT_TYPES
        from fastapi_app.tasks.report_tasks import _EXPORT_METHODS

        assert ALLOWED_REPORT_TYPES is REPORT_TYPES
        assert ASYNC_EXPORT_REPORT_TYPES is REPORT_TYPES
        assert _EXPORT_METHODS is EXPORT_METHOD_NAMES

    def test_worker_methods_resolve(self):
        from fastapi_app.tasks.report_tasks import _EXPORT_METHODS
        from utils.report_exporter import ReportExporter

        for attr in _EXPORT_METHODS.values():
            assert callable(getattr(ReportExporter, attr)), attr


class TestExportLimitMessage:
    def test_order_counts_include_both_orders_and_rows(self):
        from fastapi_app.shared.report_export import export_limit_message

        msg = export_limit_message(12000, 9000)
        assert '订单 9000 单' in msg
        assert '明细 12000 行' in msg


class _OrderStatsResult:
    def one(self):
        return (1, 10, 0, 1, 1)


class _EmptyOrderRows:
    def __iter__(self):
        return iter(())


class _OrderCaptureSession:
    def __init__(self):
        self.statements = []

    def execute(self, stmt, *args, **kwargs):
        self.statements.append(stmt)
        if len(self.statements) == 1:
            return _OrderStatsResult()
        return _EmptyOrderRows()


class TestExportOrderSecondarySort:
    def test_secondary_sort_matches_screen_desc(self):
        """屏幕用 o.id DESC；导出必须同向，且 stats 带 distinct 订单数（审计 L-21/L-22）。"""
        from sqlalchemy.dialects import postgresql

        from fastapi_app.shared.report_data_service import _get_order_logs

        session = _OrderCaptureSession()
        logs, stats = _get_order_logs(session, '', '', '', '', '')

        assert logs == []
        assert stats['order_count'] == 1
        sql = str(session.statements[1].compile(dialect=postgresql.dialect()))
        assert 'order_date DESC' in sql
        assert '"order".id DESC' in sql or 'order.id DESC' in sql


# ============================================================
# 2026-11-16 上线前审计的 5 个缺陷：回归测试
# ============================================================
# 真实 SQLAlchemy Row 才会像线上那样「没有哪一列就取不到哪个属性」。
_RETURN_ROW_SQL = (
    "SELECT 1 AS record_id, 'RT-2026-1001' AS record_no, "
    "'2026-10-13 09:30' AS return_date, '退货客户甲' AS customer, "
    "'退货产品甲' AS product_name, 'SKU-RT-1' AS product_barcode, "
    "3 AS quantity, '破损' AS reason, '已换货' AS note, 1 AS total_count"
)


def _real_return_rows():
    """用内存 sqlite 造真实 sqlalchemy.engine.Row（不连任何业务库）"""
    from sqlalchemy import create_engine, text

    engine = create_engine('sqlite://')
    try:
        with engine.connect() as conn:
            return conn.execute(text(_RETURN_ROW_SQL)).fetchall()
    finally:
        engine.dispose()


def _configure_orm_mappers():
    """构建订单查询前先配置 mapper。

    ``_get_order_logs`` 引用 ``Order.order_stockouts``——该属性由 StockOut 的 backref
    在 **mapper 配置时**注入，未经配置的 Order 类上没有它（单跑本文件会 AttributeError）。
    """
    from sqlalchemy.orm import configure_mappers

    configure_mappers()


class _FakeResult:
    def __init__(self, rows=None, scalar_value=0):
        self._rows = rows
        self._scalar_value = scalar_value

    def fetchall(self):
        return self._rows

    def scalar(self):
        return self._scalar_value


class _FakeSession:
    """只实现 _query_logs_generic 用到的 execute（明细查询返回行、数量查询返回标量）"""

    def __init__(self, rows):
        self._rows = rows

    async def execute(self, stmt, params=None):
        if 'total_count' in str(stmt):
            return _FakeResult(rows=self._rows)
        return _FakeResult(scalar_value=3)


class TestReturnLogsRecordNoMapping:
    """缺陷 1（High）：退货流水只要库里有 active 退货就整页 500。

    拦的错：SQL 别名写的是 `sr.return_no AS record_no`，row_mapper 却取
    `row.return_no` —— SQLAlchemy Row 没有 return_no 列，访问即
    `AttributeError: Could not locate column in row for column 'return_no'`，
    而 _query_logs_generic 无兜底，整页 500（筛不筛选都一样）。
    本用例**不 mock _query_logs_generic**：真实 Row 走完整查询/映射路径。
    """

    @pytest.mark.asyncio
    async def test_return_logs_map_record_no_alias(self):
        result = await get_return_logs(_FakeSession(_real_return_rows()))

        assert len(result['logs']) == 1
        log = result['logs'][0]
        assert log['record_no'] == 'RT-2026-1001'
        assert log['record_id'] == 1
        assert log['return_date'] == '2026-10-13 09:30'
        assert log['quantity'] == 3
        assert log['note_display'] == '破损；已换货'
        assert result['stats']['total_count'] == 1


class TestExportDateFilterStrict:
    """缺陷 2（High）：导出侧非法日期被静默忽略 → 拿到「全量」Excel 却以为已筛选。

    拦的错：`_apply_date_filters` 里 `except ValueError: logger.warning` 后返回
    未过滤 query，导出 200 + 全量数据（屏幕侧同样的脏值会 400）。筛错方向比报错
    危险得多：用户以为报表已按区间过滤，对账时多出来的行无法察觉。
    """

    def test_invalid_start_date_raises(self):
        from sqlalchemy import select

        from fastapi_app.shared.report_data_service import _apply_date_filters
        from fastapi_app.shared_models import Order

        with pytest.raises(ValueError, match='开始格式错误'):
            _apply_date_filters(select(Order), Order.order_date, '2026/10/01', '')

    def test_invalid_end_date_raises(self):
        from sqlalchemy import select

        from fastapi_app.shared.report_data_service import _apply_date_filters
        from fastapi_app.shared_models import Order

        with pytest.raises(ValueError, match='结束格式错误'):
            _apply_date_filters(select(Order), Order.order_date, '', '2026-13-01')

    def test_export_path_surfaces_invalid_date(self):
        """导出入口 get_all_logs_data 必须把 ValueError 抛出去（端点映射 400）"""
        from fastapi_app.shared.report_data_service import get_all_logs_data

        _configure_orm_mappers()
        with pytest.raises(ValueError):
            get_all_logs_data(MagicMock(), 'order', start_date='2026/10/01')
        with pytest.raises(ValueError):
            get_all_logs_data(MagicMock(), 'return', end_date='2026-13-01')


class TestExportQueryFailureNotSilent:
    """缺陷 5（Low）：导出查询异常被吞成「成功导出空表」。

    拦的错：get_all_logs_data 的 `except (ValueError, TypeError, OSError): return [], {}`
    把查询失败变成「0 行」，两个调用方（export_report_to_excel / report_tasks）只看
    total_count==0 → 照常生成仅表头的 xlsx 并报成功。查询失败必须与零行分开。
    """

    def test_query_error_propagates_instead_of_empty_export(self):
        from fastapi_app.shared.report_data_service import get_all_logs_data

        session = MagicMock()
        session.execute.side_effect = TypeError('驱动层失败')

        with pytest.raises(TypeError):
            get_all_logs_data(session, 'stockin')


class TestOrderNoteParity:
    """缺陷 3（Medium）：订单流水「备注」屏幕与导出两口径。

    拦的错：导出只取 order.note 并在头部拼「订单X抵扣备货Y」，屏幕是
    `item.note or order.note` —— 同一行两边备注不同，带 SKU 备注的行导出后
    SKU 备注整列丢失；抵扣串还污染了备注列。
    """

    @staticmethod
    def _screen_row(item_note: str, order_note: str):
        from types import SimpleNamespace

        return SimpleNamespace(
            order_id=7, item_id=11, order_no='SO-2026-0007',
            order_date='2026-10-13 09:00', customer='备注客户',
            product_name='备注产品', product_barcode='SKU-NOTE-1',
            quantity=2, item_note=item_note, order_note=order_note,
            item_count=1, order_total_qty=2,
        )

    @staticmethod
    def _export_rows(item_note: str, order_note: str):
        """走真实 _get_order_logs（伪会话只提供两处 execute 的返回值）"""
        from datetime import UTC, datetime
        from types import SimpleNamespace

        from fastapi_app.shared.report_data_service import _get_order_logs

        _configure_orm_mappers()
        order = SimpleNamespace(
            id=7, order_no='SO-2026-0007', customer='备注客户', status='待备货',
            order_date=datetime(2026, 10, 13, 9, 0, tzinfo=UTC),
            quantity=4, note=order_note, product_id=1,
            order_stockouts=[SimpleNamespace(quantity=3, returned_quantity=1, stockin_id=5)],
        )
        item = SimpleNamespace(
            id=11, quantity=2, product_id=1, product_name='备注产品',
            product_barcode='SKU-NOTE-1', note=item_note,
        )
        prod = SimpleNamespace(name='备注产品', barcode='SKU-NOTE-1')

        stats_result = MagicMock()
        stats_result.one.return_value = (1, 2, 0, 0, 1)
        session = MagicMock()
        session.execute.side_effect = [stats_result, iter([(order, item, prod)])]

        logs, _stats = _get_order_logs(session, '', '', '', '', '', '')
        return logs

    @pytest.mark.asyncio
    async def test_note_parity_and_deduction_split(self, mock_async_db):
        with _patch_generic() as m:
            await get_order_logs(mock_async_db)
        screen = m.call_args.kwargs['row_mapper'](
            self._screen_row(item_note='SKU 备注甲', order_note='订单备注乙'))

        exported = self._export_rows(item_note='SKU 备注甲', order_note='订单备注乙')

        assert screen['note'] == 'SKU 备注甲'
        assert exported[0]['note'] == 'SKU 备注甲'
        assert exported[0]['deduction_note'] == '订单4抵扣备货2'
        assert '抵扣备货' not in exported[0]['note']

    def test_empty_item_note_falls_back_to_order_note(self):
        exported = self._export_rows(item_note='', order_note='订单备注乙')

        assert exported[0]['note'] == '订单备注乙'

    def test_exporter_renders_deduction_note_in_own_column(self):
        import io

        from openpyxl import load_workbook

        from utils.report_exporter import ReportExporter

        data = ReportExporter().export_order_logs([{
            'order_date': '2026-10-13 09:00', 'order_no': 'SO-2026-0007',
            'customer': '备注客户', 'product_name': '备注产品',
            'product_barcode': 'SKU-NOTE-1', 'quantity': 2,
            'note': 'SKU 备注甲', 'deduction_note': '订单4抵扣备货2',
        }])
        ws = load_workbook(io.BytesIO(data)).active

        assert [c.value for c in ws[1]][-2:] == ['备注', '抵扣说明']
        assert ws.cell(row=2, column=7).value == 'SKU 备注甲'
        assert ws.cell(row=2, column=8).value == '订单4抵扣备货2'


class TestSoftDeletePredicateMatchesPartialIndex:
    """缺陷 4（Low）：软删谓词 `= false OR IS NULL` 与 partial 索引谓词不匹配。

    拦的错：改回 `(x.is_deleted = false OR x.is_deleted IS NULL)` —— 语义等价，
    但 PG 不做谓词蕴含推断，吃不到 shared_models/order.py:131 声明的
    `postgresql_where=text("is_deleted IS NOT TRUE")` 索引（查询全表扫）。
    直接对拼进查询的 SQL 文本断言，钉住三条原生 SQL 路径。
    """

    @pytest.mark.asyncio
    async def test_all_log_queries_use_is_not_true(self, mock_async_db):
        cases = [
            ('订单流水', get_order_logs),
            ('出货流水', get_stockout_logs),
            ('抵扣流水', get_deduction_logs),
        ]
        for name, endpoint in cases:
            with _patch_generic() as m:
                await endpoint(mock_async_db)
            where_sql = ' AND '.join(m.call_args.kwargs['base_where'])
            assert 'is_deleted IS NOT TRUE' in where_sql, f'{name}缺 IS NOT TRUE: {where_sql}'
            assert '= false OR' not in where_sql, f'{name}仍在用 `= false OR`: {where_sql}'
