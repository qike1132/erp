"""明细列表筛选：日期区间优先、录单人为空白即不限、区间反向报错"""
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from fastapi_app.services.daily_production_service import _build_record_conditions
from fastapi_app.shared_models import Base, DailyProductionRecord
from fastapi_app.shared_models.product import Product as ProductModel


def _texts(conditions):
    return ' | '.join(str(c) for c in conditions)


class TestRecordConditions:
    def test_year_month_only_matches_existing_behaviour(self):
        conditions = _build_record_conditions(
            year=2026, month=9, start_date='', end_date='',
            departments=None, created_by='',
        )
        assert len(conditions) == 2
        assert 'production_date' in _texts(conditions)

    def test_blank_created_by_is_not_applied(self):
        # 前端下拉清空后传 ''，绝不能退化成「只看录单人为空的记录」
        conditions = _build_record_conditions(
            year=2026, month=9, start_date='', end_date='',
            departments=None, created_by='',
        )
        assert 'created_by' not in _texts(conditions)

    def test_whitespace_created_by_is_not_applied(self):
        conditions = _build_record_conditions(
            year=2026, month=9, start_date='', end_date='',
            departments=None, created_by='   ',
        )
        assert 'created_by' not in _texts(conditions)

    def test_real_created_by_is_applied(self):
        conditions = _build_record_conditions(
            year=2026, month=9, start_date='', end_date='',
            departments=None, created_by=' 张三 ',
        )
        assert 'created_by' in _texts(conditions)

    def test_range_takes_precedence_over_year_month(self):
        conditions = _build_record_conditions(
            year=2026, month=9, start_date='2026-08-25', end_date='2026-09-02',
            departments=None, created_by='',
        )
        # 区间优先：只出现区间的两个边界，不叠加 9 月的月初/月末
        assert len(conditions) == 2
        assert conditions[0].right.value == date(2026, 8, 25)
        assert conditions[1].right.value == date(2026, 9, 2)

    def test_departments_scoped_is_applied(self):
        conditions = _build_record_conditions(
            year=2026, month=9, start_date='', end_date='',
            departments={'filling'}, created_by='',
        )
        assert 'department' in _texts(conditions)
        assert len(conditions) == 3

    def test_production_date_is_stacked_on_month_conditions(self):
        conditions = _build_record_conditions(
            year=2026, month=9, start_date='', end_date='',
            departments=None, created_by='', production_date='2026-09-15',
        )
        assert len(conditions) == 3

    def test_production_date_is_stacked_on_range_conditions(self):
        conditions = _build_record_conditions(
            year=None, month=None, start_date='2026-09-01', end_date='2026-09-30',
            departments=None, created_by='', production_date='2026-09-15',
        )
        assert len(conditions) == 3

    def test_no_date_input_at_all_raises(self):
        with pytest.raises(ValueError, match='必须提供'):
            _build_record_conditions(
                year=None, month=None, start_date='', end_date='',
                departments=None, created_by='',
            )

    def test_only_start_date_raises(self):
        with pytest.raises(ValueError, match='必须同时提供'):
            _build_record_conditions(
                year=None, month=None, start_date='2026-09-01', end_date='',
                departments=None, created_by='',
            )

    def test_reversed_range_raises(self):
        with pytest.raises(ValueError, match='不能早于'):
            _build_record_conditions(
                year=None, month=None, start_date='2026-09-10', end_date='2026-09-01',
                departments=None, created_by='',
            )

    def test_blank_keyword_is_not_applied(self):
        conditions = _build_record_conditions(
            year=2026, month=9, start_date='', end_date='',
            departments=None, created_by='', keyword='',
        )
        assert 'product_name' not in _texts(conditions)

    def test_whitespace_keyword_is_not_applied(self):
        conditions = _build_record_conditions(
            year=2026, month=9, start_date='', end_date='',
            departments=None, created_by='', keyword='   ',
        )
        assert 'product_name' not in _texts(conditions)

    def test_keyword_matches_product_name_or_barcode(self):
        conditions = _build_record_conditions(
            year=2026, month=9, start_date='', end_date='',
            departments=None, created_by='', keyword='白兔',
        )
        rendered = _texts(conditions)
        assert 'product_name' in rendered
        assert 'barcode' in rendered
        assert len(conditions) == 3

    def test_keyword_like_wildcards_are_escaped(self):
        conditions = _build_record_conditions(
            year=2026, month=9, start_date='', end_date='',
            departments=None, created_by='', keyword='50%',
        )
        # 注意：str(条件) 只渲染绑定占位符（如 :product_name_1），字面量不在其中，
        # 故直接取 LIKE 子句的绑定参数值断言。必须是转义后的字面量，而不是裸的 %
        # 通配 —— 否则 '50%' 会被当成「以 50 开头」，静默返回错误结果。
        like_clause = next(c for c in conditions[2].clauses if 'LIKE' in str(c))
        assert like_clause.right.value == '%50\\%%'
        # 仅断言绑定值还不够：把 like(pattern, escape='\\') 里的 escape= 删掉，
        # 上面的断言依然通过（SQLAlchemy 只是不再声明转义符）。渲染出的子句文本
        # 必须真的带 ESCAPE，才能证明 escape 参数被传进了 SQL。
        assert 'ESCAPE' in str(like_clause)


class TestStatsCteEffectivePrice:
    """页脚合计产值与列内各行之和同口径（unit_price=0 时回退产品当前价）。

    行内展示（to_dict + _build_product_price_fallback）在记录单价为 0 时
    回退到 Product.price，而统计 CTE 此前直接 sum(记录单价×数量) ——
    于是"录了 0 价"的记录行内显示非零产值、页脚却记 0，合计会低于列内之和。
    本用例用内存 SQLite 跑真实 SQL，证伪该回归。
    """

    async def test_footer_total_equals_sum_of_rows_when_stored_price_is_zero(self):
        engine = create_async_engine(
            'sqlite+aiosqlite:///:memory:',
            poolclass=StaticPool,
            connect_args={'check_same_thread': False},
        )
        async with engine.begin() as conn:
            await conn.run_sync(lambda c: Base.metadata.create_all(
                c, tables=[DailyProductionRecord.__table__, ProductModel.__table__],
            ))
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as db:
            db.add(ProductModel(id=1, name='白兔公仔', price=7))
            # 一条单价 0（回退产品价 7）、一条单价 5 —— 两种口径都要算进合计
            db.add(DailyProductionRecord(
                id=1, department='filling', product_id=1, product_name='白兔公仔',
                barcode='', unit_price=0, quantity=100, production_date=date(2026, 9, 29),
            ))
            db.add(DailyProductionRecord(
                id=2, department='handcraft', product_id=1, product_name='白兔公仔',
                barcode='', unit_price=5, quantity=10, production_date=date(2026, 9, 29),
            ))
            await db.flush()

            from fastapi_app.services.daily_production_service import get_records
            result = await get_records(db, year=2026, month=9)

            rows_sum = round(sum(r['production_value'] for r in result['data']), 2)
            assert rows_sum == 750  # 7×100 + 5×10，行内展示用的是回退价
            assert result['stats']['total_value'] == rows_sum
        await engine.dispose()
