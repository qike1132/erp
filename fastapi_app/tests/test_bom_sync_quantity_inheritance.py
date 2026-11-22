"""BOM 同步多对一合并不得用首条旧行数量覆盖重算数量（审计 H-1）。"""
from __future__ import annotations

from decimal import Decimal

from fastapi_app.services.purchase.bom_sync import _inherit_fields
from fastapi_app.shared_models.purchase_order import PurchaseOrderItem


def _old_row(**overrides) -> PurchaseOrderItem:
    """未落库的 ORM 行：_inherit_fields 只读属性，不碰数据库。"""
    base: dict = {
        'order_id': 1,
        'material_name': '皮革',
        'specification': '120cm',
        'unit': '米',
        'part_name': '身体',
        'supplier_name': '供应商A',
        'material_category': '面料',
        'role_id': None,
        'loss_rate': Decimal('0.05'),
        'unit_price': Decimal('10.00'),
        'remark': '来源BOM：白款',
        'quantity': Decimal('100'),
        'unit_usage': Decimal('2'),
    }
    base.update(overrides)
    return PurchaseOrderItem(**base)


def _target(**overrides) -> dict:
    base: dict = {
        'material_name': '皮革',
        'specification': '120cm',
        'unit': '米',
        'part_name': '身体',
        'supplier_name': '供应商A',
        'category': '面料',
        'role_id': None,
        'quantity': Decimal('100'),
        'unit_usage': Decimal('2'),
    }
    base.update(overrides)
    return base


def test_many_to_one_preserves_recalculated_quantity():
    """两条 0.13 旧行合并为重算总量 0.26，不得退回首条的 0.13。"""
    rows = [
        _old_row(quantity=Decimal('0.13')),
        _old_row(quantity=Decimal('0.13')),
    ]
    target = [_target(quantity=Decimal('0.26'))]

    _inherit_fields(rows, target)

    assert target[0]['quantity'] == Decimal('0.26')
    assert target[0]['loss_rate'] == Decimal('0.05')
    assert target[0]['unit_price'] == Decimal('10.00')
    assert target[0]['remark'] == '来源BOM：白款'


def test_one_to_one_still_inherits_custom_quantity():
    target = [_target(quantity=Decimal('80'))]

    _inherit_fields([_old_row(quantity=Decimal('100'))], target)

    assert target[0]['quantity'] == Decimal('100')


def test_one_to_many_behavior_is_unchanged():
    """首行消费旧数量，其余新增行保留各自重算数量。"""
    target = [
        _target(quantity=Decimal('40')),
        _target(quantity=Decimal('60')),
    ]

    _inherit_fields([_old_row(quantity=Decimal('100'))], target)

    assert [item['quantity'] for item in target] == [Decimal('100'), Decimal('60')]


def test_changed_unit_usage_does_not_inherit_quantity():
    target = [_target(quantity=Decimal('150'), unit_usage=Decimal('3'))]

    _inherit_fields(
        [_old_row(quantity=Decimal('100'), unit_usage=Decimal('2'))],
        target,
    )

    assert target[0]['quantity'] == Decimal('150')
