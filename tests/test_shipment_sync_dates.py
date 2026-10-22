"""M6：出货同步的目标日期必须是业务昨日，并回看 N 天。"""
from datetime import date


def test_target_dates_use_business_yesterday():
    from fastapi_app.tasks.plan_tasks import _sync_target_dates

    assert _sync_target_dates(date(2026, 10, 22), 3) == [
        date(2026, 10, 21),
        date(2026, 10, 20),
        date(2026, 10, 19),
    ]
