"""采购计划响应契约：进度字段名与口径

口径已从「已出货」改为「已生产」（数据源 daily_production_record）。
这里钉住响应契约里**唯一**由 Pydantic 显式声明的那处改名 ——
MonthlyAggregatedResponse / MonthlyCalendarResponse 的明细是 list[dict] 透传，
契约由前端 TS 类型与挂载测试承担，不在本文件覆盖。
"""
from fastapi_app.schemas.purchase_plan import DayDetailsResponse


class TestDayDetailsResponseContract:
    def test_exposes_produced_pct(self):
        assert 'produced_pct' in DayDetailsResponse.model_fields

    def test_no_longer_exposes_shipped_pct(self):
        """是改名不是新增别名：留着旧名会让前端悄悄读到口径已变的旧字段"""
        assert 'shipped_pct' not in DayDetailsResponse.model_fields
