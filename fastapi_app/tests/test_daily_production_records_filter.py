"""明细列表筛选：日期区间优先、录单人为空白即不限、区间反向报错"""
from datetime import date

import pytest

from fastapi_app.services.daily_production_service import _build_record_conditions


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
