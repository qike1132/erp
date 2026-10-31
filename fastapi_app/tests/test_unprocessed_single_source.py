"""未处理记录：页面显示与自动生成必须共用同一份 SQL（2026-10-30 审计 A-M20）。

背景：`purchase_order_query.py` 里曾**复制**一份「Order 待备货 + StockIn」的
UNION ALL 构造，与 `purchase/_unprocessed.py` 的实现并存。前者决定「待审核页面
显示什么」，后者决定「自动生成采购单时取哪些记录」——两处一旦分叉，就会出现
「页面上一直看得到、却永远不被自动生成」的静默漏单（或反向重复生成）。

本测试把「只有一个实现」钉成可执行断言：两条入口生成的 SQL 文本必须逐字相同，
且页面入口不得再持有自己的 `union_all(...)`。
"""
import inspect

from fastapi_app.services import purchase_order_query as poq
from fastapi_app.services.purchase._unprocessed import (
    _build_not_processed_filter,
    _build_unprocessed_union,
)


def test_page_and_auto_generate_produce_identical_sql():
    """两种 sku_available 取值下，页面入口与自动生成入口的 SQL 完全一致。"""
    for sku_available in (True, False):
        page_sql = str(poq._build_unprocessed_unified_query(sku_available))
        worker_sql = str(_build_unprocessed_union(sku_available))
        assert page_sql == worker_sql, f'sku_available={sku_available} 时两处 SQL 分叉'


def test_page_builder_delegates_instead_of_copying():
    """页面入口只做委托：源码里不得再出现 union_all( 的 SQL 副本。"""
    src = inspect.getsource(poq._build_unprocessed_unified_query)
    assert '_build_unprocessed_union' in src
    assert 'union_all(' not in src


def test_not_processed_filter_is_the_same_object_everywhere():
    """NOT EXISTS 过滤（含 P1 的类型化判定）在两条链路上必须是同一个函数对象。

    历史事故：`source_order_ids` 只比裸 id，order.id 与 stockin.id 撞号时把另一类型
    记录误判为「已处理」→ 记录从待审核列表消失且永不自动生成。
    """
    from fastapi_app.services.purchase_order_query_helpers import (
        _build_not_processed_filter as via_helpers,
    )

    assert via_helpers is _build_not_processed_filter
    assert poq._build_not_processed_filter is _build_not_processed_filter


def test_union_covers_both_sources_and_excludes_processed():
    sql = str(_build_unprocessed_union(True)).upper()
    assert 'UNION ALL' in sql
    assert 'PURCHASE_ORDER_SKU' in sql  # 类型化「已处理」判定
    assert 'NOT (' in sql or 'NOT EXISTS' in sql
