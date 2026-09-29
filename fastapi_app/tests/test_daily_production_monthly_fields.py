"""锁死月度汇总的字段口径漂移

背景（设计规格 §1.2 D-2 缺陷）：前端曾读 `overall_quantity`、而后端返回
`monthly_total_quantity`，`?? 0` 兜底掩盖了字段名不匹配，导致月报两个
头部 KPI 恒为 0。本文件把"三个口径必须一致"钉死。

注意：部门范围过滤在 SQL 的 WHERE 里完成，mock 会话不会执行它，因此
"范围外部门被排除"的断言在 test_daily_production_dept_scope.py 用端点
层测试覆盖；本文件只锁服务层输出的内部一致性与结构契约。
"""
from collections import namedtuple
from datetime import date
from unittest.mock import AsyncMock, MagicMock

from fastapi_app.services.daily_production_service import get_monthly_summary

# 服务层按列名取数（`row.production_date` / `row.total_qty` ...），真实
# SQLAlchemy `.all()` 返回的 Row 正是这种「可按属性访问的类元组」。测试里的
# 行字面量写成普通元组便于阅读，这里统一包成同形状的 Row 替身，避免 mock
# 与生产取数方式不一致造成假失败。
_MonthlyRow = namedtuple(
    '_MonthlyRow', 'production_date department total_qty total_val sku_count'
)


def _mock_db_returning(rows):
    result = MagicMock()
    result.all.return_value = [_MonthlyRow(*r) for r in rows]
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    return db


class TestMonthlySummaryFieldConsistency:
    async def test_monthly_total_matches_daily_and_department_sums(self):
        rows = [
            (date(2026, 9, 1), 'filling', 100, 700.0, 2),
            (date(2026, 9, 1), 'handcraft', 40, 360.0, 1),
            (date(2026, 9, 2), 'packaging', 7, 35.0, 1),
        ]
        db = _mock_db_returning(rows)

        out = await get_monthly_summary(db, 2026, 9)

        assert out['monthly_total_quantity'] == 147
        assert sum(d['total']['quantity'] for d in out['daily_data']) == 147
        assert sum(d['total_quantity'] for d in out['monthly_departments']) == 147

    async def test_every_day_carries_all_department_keys_and_total(self):
        # 前端按固定键名取数，键缺失会让整页崩在 Undefined 上
        db = _mock_db_returning([])

        out = await get_monthly_summary(db, 2026, 2)

        assert len(out['daily_data']) == 28
        for day in out['daily_data']:
            for key in ('filling', 'handcraft', 'packaging', 'total'):
                assert key in day
