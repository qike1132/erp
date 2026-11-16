"""BOM 保存重建 pending 采购单时，明细备注必须继承（2026-11-16 上线前审计 A-23）。

拦哪种错：回退键（改部位 / 新增行）那条路径把 ``remark`` 丢掉了，于是重建后
「来源BOM：<角色>」整列变 NULL，与生成路径（``purchase_order_crud.py:158`` 写
``_scope_remark``）不同源——采购员看不出这条需求由谁产生。

变异检查：把 ``fallback_pool[fb]`` 改回只装 ``(loss_rate, unit_price)``，
下面第 2 条用例必红。
"""
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
        'quantity': 100,
        'unit_usage': 2,
    }
    base.update(overrides)
    return base


def test_exact_key_inherits_remark():
    target = [_target()]
    _inherit_fields([_old_row()], target)
    assert target[0]['remark'] == '来源BOM：白款'


def test_fallback_key_inherits_remark_too():
    """改部位的行只能命中回退键 —— 这里也必须把 remark 带过去。"""
    target = [_target(part_name='脚底')]
    _inherit_fields([_old_row()], target)

    assert target[0]['loss_rate'] == Decimal('0.05')
    assert target[0]['unit_price'] == Decimal('10.00')
    assert target[0]['remark'] == '来源BOM：白款', (
        '改部位/新增行走回退键时 remark 被丢掉：重建后「来源BOM」整列变 NULL'
    )


def test_new_item_without_old_row_does_not_fabricate_remark():
    """没有对应旧行时不得伪造备注（保持缺失，由重建路径补 scope label）。"""
    target = [_target(part_name='鞋带', material_name='织带')]
    _inherit_fields([_old_row()], target)
    assert 'remark' not in target[0]
