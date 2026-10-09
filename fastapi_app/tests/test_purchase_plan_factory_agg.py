"""备货计划聚合的工厂维度单元测试。

背景：/purchase-plan 需要按工厂（东莞/湖北）拆分查看。工厂来自 product.factory，
经 purchase_plan_details.product_id 关联。本测试钉住聚合层把 factory 透传到
rows / sku_summary / sku_date_index / customers 四个出口的行为，不依赖数据库。
"""
from datetime import date
from types import SimpleNamespace

from fastapi_app.services.purchase_plan_queries import (
    _aggregate_monthly_rows,
    _build_customer_totals,
    _build_monthly_rows_list,
    _build_sku_summary_list,
)


def _row(detail_id, customer_id, customer_name, product_name, barcode, plan_date, quantity, factory):
    return SimpleNamespace(
        detail_id=detail_id, plan_id=1, customer_id=customer_id,
        customer_name=customer_name, product_name=product_name, barcode=barcode,
        plan_date=plan_date, quantity=quantity, factory=factory,
    )


def _aggregate(rows, produced):
    return _aggregate_monthly_rows(rows, produced, {})


class TestFactoryAggregation:
    def test_date_breakdown_and_combined_totals(self):
        """同一天含两个工厂：combined 合计不变，factories 里按厂拆分。"""
        rows = [
            _row(1, 1, '客户甲', '产品A', '6901', date(2026, 4, 15), 100, '东莞'),
            _row(2, 1, '客户甲', '产品B', '6902', date(2026, 4, 15), 50, '湖北'),
        ]
        by_date, _by_key, _idx, _ps = _aggregate(rows, {1: 100, 2: 20})
        rows_list = _build_monthly_rows_list(by_date, 4)
        d15 = next(r for r in rows_list if r['date'] == '2026-04-15')

        assert d15['totalQty'] == 150
        assert d15['factories']['东莞']['qty'] == 100
        assert d15['factories']['东莞']['produced'] == 100
        assert d15['factories']['东莞']['pct'] == 100.0
        assert d15['factories']['湖北']['qty'] == 50
        assert d15['factories']['湖北']['produced'] == 20
        assert d15['factories']['湖北']['pct'] == 40.0
        # 行计数与日级同口径：东莞 1 行已完成、湖北 1 行未完成
        assert d15['factories']['东莞']['rowN'] == 1
        assert d15['factories']['东莞']['completedN'] == 1
        assert d15['factories']['东莞']['pendingN'] == 0
        assert d15['factories']['湖北']['rowN'] == 1
        assert d15['factories']['湖北']['completedN'] == 0
        assert d15['factories']['湖北']['pendingN'] == 1
        # 客户名按厂收敛（前端按厂筛选后重算导出/风险清单用）
        assert d15['factories']['东莞']['custNames'] == ['客户甲']
        assert d15['factories']['湖北']['custNames'] == ['客户甲']

    def test_factory_counts_are_per_factory(self):
        """同一工厂下多客户/多产品，custN/prodN 只数该厂自己的。"""
        rows = [
            _row(1, 1, '客户甲', '产品A', '6901', date(2026, 4, 15), 100, '东莞'),
            _row(2, 2, '客户乙', '产品B', '6902', date(2026, 4, 15), 80, '东莞'),
            _row(3, 1, '客户甲', '产品C', '6903', date(2026, 4, 15), 50, '湖北'),
        ]
        by_date, *_ = _aggregate(rows, {})
        d15 = _build_monthly_rows_list(by_date, 4)[0]

        assert d15['factories']['东莞']['custN'] == 2
        assert d15['factories']['东莞']['prodN'] == 2
        assert d15['factories']['湖北']['custN'] == 1
        assert d15['factories']['湖北']['prodN'] == 1

    def test_sku_summary_carries_factory(self):
        rows = [
            _row(1, 1, '客户甲', '产品A', '6901', date(2026, 4, 15), 100, '东莞'),
            _row(2, 1, '客户甲', '产品B', '6902', date(2026, 4, 15), 50, '湖北'),
        ]
        _bd, by_key, _idx, _ps = _aggregate(rows, {1: 100, 2: 20})
        sku = _build_sku_summary_list(by_key)
        got = {s['product_name']: s['factory'] for s in sku}
        assert got == {'产品A': '东莞', '产品B': '湖北'}

    def test_sku_date_index_carries_factory(self):
        rows = [
            _row(1, 1, '客户甲', '产品B', '6902', date(2026, 4, 15), 50, '湖北'),
        ]
        _bd, _bk, idx, _ps = _aggregate(rows, {})
        # _prod_cust_date_map 的值是按日期索引的 dict（转成 list 发生在 get_monthly_aggregated）
        assert idx['客户甲|产品B']['2026-04-15']['factory'] == '湖北'

    def test_customer_totals_split_by_factory(self):
        rows = [
            _row(1, 1, '客户甲', '产品A', '6901', date(2026, 4, 15), 100, '东莞'),
            _row(2, 1, '客户甲', '产品B', '6902', date(2026, 4, 15), 50, '湖北'),
        ]
        _bd, _bk, _idx, psum = _aggregate(rows, {1: 100, 2: 20})
        customers, _totals = _build_customer_totals(psum)
        c1 = next(c for c in customers if c['customer_id'] == 1)

        assert c1['plan_qty'] == 150
        assert c1['factories']['东莞']['plan_qty'] == 100
        assert c1['factories']['湖北']['plan_qty'] == 50
        assert c1['factories']['湖北']['produced_qty'] == 20

    def test_null_factory_falls_back_to_placeholder(self):
        """产品未标工厂（factory=NULL）也要归到一个稳定桶，不能丢数据。"""
        rows = [
            _row(1, 1, '客户甲', '产品A', '6901', date(2026, 4, 15), 100, None),
        ]
        _bd, by_key, idx, _psum = _aggregate(rows, {})
        sku = _build_sku_summary_list(by_key)
        d15 = _build_monthly_rows_list(_bd, 4)[0]

        assert sku[0]['factory'] == '未标注'
        assert '未标注' in d15['factories']
        assert d15['factories']['未标注']['qty'] == 100
        assert idx['客户甲|产品A']['2026-04-15']['factory'] == '未标注'
