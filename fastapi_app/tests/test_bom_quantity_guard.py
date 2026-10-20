"""F6-1：BOM 用量/数量负数必须在落库前拒绝（原先静默入库，下游按 >0 判无物料）。"""
from decimal import Decimal

import pytest

from fastapi_app.services.bom_service import _non_negative_decimal


def test_negative_quantity_rejected():
    with pytest.raises(ValueError, match='不能为负数'):
        _non_negative_decimal(-1, '物料数量')


def test_zero_and_none_allowed():
    assert _non_negative_decimal(0, '物料数量') == Decimal('0')
    assert _non_negative_decimal(None, '充棉用量') == Decimal('0')


def test_positive_value_preserved():
    assert _non_negative_decimal('2.50', '物料数量') == Decimal('2.50')
