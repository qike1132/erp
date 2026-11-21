"""M-9 / M-12 回归（2026-11-21 全量审计）。

M-9：皮套流水导出此前超限静默截尾（用户拿到缺行 Excel 无从察觉）——
超限抛 ValueError，端点映射 413（A-M24 口径）。
M-12：来料登记此前可无痕删除已收货的登记——收货台账消失、采购进度归零
可重复收货。修复：有收货行时拒绝删除。
"""
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from fastapi_app.services.case.queries import fetch_movements_for_export
from fastapi_app.services.material_registration import _commands as mat_cmds
from fastapi_app.shared_models import (
    Case,
    CaseMovement,
    MaterialRegistration,
    MaterialRegistrationItem,
    PurchaseOrder,
)


async def test_case_movements_export_rejects_over_limit(app_on_test_db, async_db_session):
    db = async_db_session
    case = Case(name='导出限额皮套', current_stock=0)
    db.add(case)
    await db.flush()
    for i in range(3):
        db.add(CaseMovement(
            case_id=case.id, direction='out', movement_no=f'CSO-LIM-{i}',
            quantity=1, customer='客户甲',
            movement_date=datetime(2026, 11, 1, 5, i, tzinfo=UTC),
        ))
    await db.flush()

    # CI 教训：不带 case_id 是全表口径，会数进其他测试留下的流水（全量跑次序
    # 与本地不同）——限额与行数断言都按 case_id 过滤，与生产导出用法一致。
    with pytest.raises(ValueError, match='超过单次导出上限'):
        await fetch_movements_for_export(db, case_id=case.id, limit=2)
    # 未超限时正常返回（防修复误伤）
    rows = await fetch_movements_for_export(db, case_id=case.id, limit=10)
    assert len(rows) == 3


async def _make_registration(db, po_no: str) -> MaterialRegistration:
    from uuid import uuid4
    po = PurchaseOrder(order_no=f'M12-{uuid4().hex[:8]}', supplier_name='供应商甲',
                       customer_name='客户甲', status='pending')
    db.add(po)
    await db.flush()
    reg = MaterialRegistration(purchase_order_id=po.id, purchase_order_no=po_no)
    db.add(reg)
    await db.flush()
    return reg


async def test_material_delete_rejects_when_received(app_on_test_db, async_db_session):
    db = async_db_session
    reg = await _make_registration(db, 'M12-PO-1')
    db.add(MaterialRegistrationItem(
        registration_id=reg.id, material_name='物料甲', received_quantity=5))
    await db.flush()

    with pytest.raises(ValueError, match='已有收货记录'):
        await mat_cmds.delete_registration(db, reg.id)
    left = (await db.execute(
        select(func.count()).select_from(MaterialRegistration)
    )).scalar()
    assert left == 1


async def test_material_delete_allows_unreceived(app_on_test_db, async_db_session):
    db = async_db_session
    reg = await _make_registration(db, 'M12-PO-2')
    db.add(MaterialRegistrationItem(
        registration_id=reg.id, material_name='物料乙', received_quantity=0))
    await db.flush()

    result = await mat_cmds.delete_registration(db, reg.id)
    assert result['success'] is True
