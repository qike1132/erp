"""L1：日报金额舍入必须在 Decimal 上做，float 只在 JSON 边界出现。"""
from decimal import Decimal


def test_money_to_json_rounds_decimal_half_up():
    from fastapi_app.services.daily_production_service import _money_to_json

    assert _money_to_json(Decimal('1.005')) == 1.01
    assert _money_to_json(Decimal('2.675')) == 2.68
    # 关键：float 中转会把「略小于 1.005」压成 1.005 再进 HALF-UP，多进一分
    assert _money_to_json(Decimal('1.0049999999999999999')) == 1.0


def test_sum_money_accumulates_in_decimal():
    from fastapi_app.services.daily_production_service import _sum_money_to_json

    assert _sum_money_to_json([0.1, 0.2]) == 0.3
    assert _sum_money_to_json([0.005, 0.005]) == 0.01
    assert _sum_money_to_json([]) == 0.0
