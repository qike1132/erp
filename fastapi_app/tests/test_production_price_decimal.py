"""M-17 回归：生产记录单价 Decimal 单源（2026-11-21 全量审计）。

schema 此前 ``unit_price: float`` 直入（库列 Decimal），且列表/导出两条路径
各持一份 effective_unit_price 实现（Decimal/float 各一）。修复：schema 收
Decimal（pydantic 对 JSON number 自动收敛，契约兼容），两路径共用模块级
_effective_unit_price 唯一实现，Excel 展示层才转 float。
"""
from decimal import Decimal

from fastapi_app.schemas.daily_production import ProductionRecordCreate, ProductionRecordUpdate
from fastapi_app.services.daily_production_service import _effective_unit_price


def test_schema_coerces_float_price_to_decimal():
    created = ProductionRecordCreate(
        department='filling', product_name='产品甲', quantity=10,
        unit_price=1.5, production_date='2026-11-21')
    assert created.unit_price == Decimal('1.5')
    assert isinstance(created.unit_price, Decimal)


def test_update_schema_accepts_decimal():
    updated = ProductionRecordUpdate(unit_price=Decimal('2.25'))
    assert updated.unit_price == Decimal('2.25')


def test_effective_unit_price_prefers_record_price():
    r = type('R', (), {'unit_price': Decimal('3.5'), 'product_id': 1})()
    assert _effective_unit_price(r, {1: Decimal('9')}) == Decimal('3.5')


def test_effective_unit_price_falls_back_to_product_price():
    r = type('R', (), {'unit_price': None, 'product_id': 1})()
    assert _effective_unit_price(r, {1: Decimal('9.9')}) == Decimal('9.9')


def test_effective_unit_price_zero_when_no_fallback():
    r = type('R', (), {'unit_price': None, 'product_id': None})()
    assert _effective_unit_price(r, {}) == Decimal('0')
