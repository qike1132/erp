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

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from fastapi_app.services.daily_production_service import get_monthly_summary
from fastapi_app.shared_models import Base, DailyProductionRecord
from fastapi_app.shared_models.product import Product as ProductModel

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


class TestMonthlySkuDedup:
    """审计 #7：SKU 数一律「先去重再计数」，不得把按日按部门的 distinct 数相加。

    这是两套口径被混淆的经典形态：`count(distinct product_name)` 对一个 (日, 部门)
    单元格是对的，但把它跨天、跨部门**求和**就等于把「集合大小」当「可加量」，
    同一产品跨 2 天 × 2 部门会被数成 4 个 SKU。

    用内存 SQLite 跑真实 SQL：口径错误只有真 SQL 才暴露（mock 回来的行是测试自己
    造的，求和与去重都由被测代码决定，镜像断言会一起变绿）。
    """

    async def test_same_product_across_days_and_departments_counts_once(self):
        engine = create_async_engine(
            'sqlite+aiosqlite:///:memory:',
            poolclass=StaticPool,
            connect_args={'check_same_thread': False},
        )
        async with engine.begin() as conn:
            await conn.run_sync(
                lambda c: Base.metadata.create_all(
                    c, tables=[DailyProductionRecord.__table__, ProductModel.__table__],
                )
            )
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as db:
            # 白兔公仔：09-01 / 09-02 两天，充棉部与包装部都做过
            for rid, (dept, day, name) in enumerate([
                ('filling', 1, '白兔公仔'),
                ('filling', 2, '白兔公仔'),
                ('packaging', 1, '白兔公仔'),
                ('packaging', 2, '白兔公仔'),
                # 黑猫公仔只为证明去重没有「一律算 1」
                ('packaging', 2, '黑猫公仔'),
            ], start=1):
                db.add(DailyProductionRecord(
                    id=rid, department=dept, product_name=name, barcode='',
                    unit_price=5, quantity=10, production_date=date(2026, 9, day),
                ))
            await db.flush()

            out = await get_monthly_summary(db, 2026, 9)

        await engine.dispose()

        by_dept = {d['department']: d['sku_count'] for d in out['monthly_departments']}
        # 拦的错：旧写法 sum(每日 distinct) → 充棉部 2、包装部 2（合计 4）
        assert by_dept['filling'] == 1
        assert by_dept['packaging'] == 2  # 白兔 + 黑猫
        by_day = {d['date']: d['total']['sku_count'] for d in out['daily_data']}
        # 拦的错：日合计曾把三个部门的 distinct 数相加，同一天跨部门就重复计数
        assert by_day['2026-09-01'] == 1
        assert by_day['2026-09-02'] == 2
        # 空日期仍是 0（缺省条目不得被去重逻辑漏成 None）
        assert by_day['2026-09-03'] == 0

