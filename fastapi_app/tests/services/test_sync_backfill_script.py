"""存量 pending 采购单 BOM 校正脚本测试（task-8）。

覆盖：dry-run 四类清单与零写入、apply 后差异归零且版本递增、
手工行在 removed 中标记 suspected_manual、跨部位旧行不被误标、
--product-id 限定范围、unresolved 单报告且不写库。

夹具为本地小型副本（pytest 夹具跨模块不自动可用；种子形态参照
``test_bom_sync.py`` 的 sqlite 内存库风格，只建本测试触及的表）。
"""
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from fastapi_app.shared_models import (
    Base,
    Order,
    OrderItem,
    Product,
    ProductAccessory,
    ProductFabric,
    ProductMaterial,
    ProductRole,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderSku,
)
from fastapi_app.shared_models.purchase_center import ModificationLog
from scripts.sync_pending_po_items import run_backfill


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    tables = [PurchaseOrder.__table__, PurchaseOrderItem.__table__, PurchaseOrderSku.__table__,
              Order.__table__, OrderItem.__table__, Product.__table__,
              ProductFabric.__table__, ProductAccessory.__table__, ProductRole.__table__,
              ProductMaterial.__table__, ModificationLog.__table__]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    maker = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


_UNSET = object()


def _row(material_name, specification='', unit='', *, qty, part=None,
         supplier='', category='fabric', unit_usage=1.0):
    return {'material_name': material_name, 'specification': specification,
            'unit': unit, 'part_name': part, 'supplier_name': supplier,
            'material_category': category, 'quantity': qty, 'unit_usage': unit_usage}


async def _seed(session, *, pid, po_id, order_id, product_name, fabric_name,
                fabric_spec='', fabric_unit='码', fabric_supplier='美利达',
                fabric_part=None, accessory_name=None,
                sku_name=None, source_order_ids=_UNSET, old_rows=()):
    """非盲盒产品（单 BOM 作用域）+ 一张 pending 采购单 + 旧明细快照。"""
    session.add(Product(id=pid, name=product_name, is_blind_box=False,
                        has_hidden_role=False))
    session.add(ProductFabric(
        id=pid * 100 + 1, product_id=pid, role_id=None, fabric_name=fabric_name,
        specification=fabric_spec, unit=fabric_unit, quantity=1.0,
        part_name=fabric_part, supplier_name=fabric_supplier))
    if accessory_name:
        session.add(ProductAccessory(
            id=pid * 100 + 2, product_id=pid, role_id=None,
            accessory_name=accessory_name, specification='1条', unit='个',
            quantity=1.0, supplier_name='木棒'))
    session.add(Order(id=order_id, order_no=f'SO-{order_id}', customer='客户甲',
                      product_id=pid, quantity=10000, status='已备货'))
    session.add(OrderItem(id=order_id * 10 + 1, order_id=order_id, product_id=pid,
                          product_name=product_name, quantity=10000))
    if source_order_ids is _UNSET:
        source_order_ids = f'[{order_id}]'
    session.add(PurchaseOrder(
        id=po_id, order_no=f'PO-{po_id}', customer_name='客户甲',
        product_name=sku_name or product_name, product_quantity=10000,
        supplier_name=fabric_supplier, source_order_ids=source_order_ids,
        status='pending'))
    session.add(PurchaseOrderSku(
        id=po_id, po_id=po_id, product_name=sku_name or product_name,
        product_barcode='', order_qty=10000, source_order_id=order_id,
        source_record_type='order'))
    for idx, row in enumerate(old_rows, start=1):
        session.add(PurchaseOrderItem(id=po_id * 10 + idx, order_id=po_id, **row))
    await session.commit()


async def _seed_base(db):
    """PO 8301：旧行需改量 + 一条手工孤儿行；PO 8302：需改量（第二产品）。"""
    await _seed(db, pid=301, po_id=8301, order_id=9301, product_name='产品C',
                fabric_name='绿色超柔', fabric_spec='234', fabric_unit='码',
                fabric_part='身体', fabric_supplier='美利达',
                accessory_name='木棒按摩锤', old_rows=[
                    _row('绿色超柔', '234', '码', qty=50, part='身体',
                         supplier='美利达', category='fabric'),
                    _row('手工辅料', '', '个', qty=5, part=None,
                         supplier='某厂', category='accessory'),
                ])
    await _seed(db, pid=302, po_id=8302, order_id=9302, product_name='产品D',
                fabric_name='红色绒', fabric_spec='556', fabric_unit='码',
                fabric_supplier='供应商乙', old_rows=[
                    _row('红色绒', '556', '码', qty=10, supplier='供应商乙',
                         category='fabric'),
                ])


async def _items(db):
    rows = (await db.execute(
        select(PurchaseOrderItem)
        .order_by(PurchaseOrderItem.order_id, PurchaseOrderItem.id)
    )).scalars().all()
    return [(r.id, r.order_id, r.material_name, float(r.quantity)) for r in rows]


async def test_dry_run_reports_four_lists_without_writing(db):
    await _seed_base(db)
    before = await _items(db)

    report = await run_backfill(db, dry_run=True)

    assert report.dry_run is True
    assert report.scanned == 2
    assert report.affected_po_ids == [8301, 8302]

    # ① 数量变更行（旧→新）
    changed = {(r['po_id'], r['material_name']): r for r in report.changed}
    assert set(changed) == {(8301, '绿色超柔'), (8302, '红色绒')}
    assert changed[(8301, '绿色超柔')]['old_quantity'] == 50.0
    assert changed[(8301, '绿色超柔')]['new_quantity'] == 10000.0
    # ② 新增行（新 BOM 的辅料桶）
    assert [(r['po_id'], r['material_name']) for r in report.added] == \
        [(8301, '木棒按摩锤')]
    # ③ 删除行：手工孤儿行被标记
    assert [(r['po_id'], r['material_name'], r['suspected_manual'])
            for r in report.removed] == [(8301, '手工辅料', True)]
    # ④ 无解析失败
    assert report.unresolved == []
    assert report.errors == []

    # dry-run 绝不写库：明细原样、版本不变、无审计
    assert await _items(db) == before
    assert (await db.execute(
        select(func.count()).select_from(ModificationLog))).scalar() == 0
    for po_id in (8301, 8302):
        assert (await db.get(PurchaseOrder, po_id)).items_version == 0


async def test_apply_writes_then_second_dry_run_is_clean(db):
    await _seed_base(db)

    report = await run_backfill(db, dry_run=False)
    assert report.dry_run is False
    assert len(report.changed) == 2
    assert len(report.added) == 1
    assert len(report.removed) == 1
    assert report.errors == []

    assert (await db.get(PurchaseOrder, 8301)).items_version == 1
    assert (await db.get(PurchaseOrder, 8302)).items_version == 1
    rows_8301 = (await db.execute(
        select(PurchaseOrderItem).where(PurchaseOrderItem.order_id == 8301)
    )).scalars().all()
    assert sorted((r.material_name, float(r.quantity)) for r in rows_8301) == \
        [('木棒按摩锤', 10000.0), ('绿色超柔', 10000.0)]  # 手工行已删除

    # 幂等：再跑 dry-run 四类清单为空，版本不再递增
    again = await run_backfill(db, dry_run=True)
    assert again.changed == [] and again.added == [] and again.removed == []
    assert again.affected_po_ids == []
    assert again.unresolved == [] and again.errors == []
    assert (await db.get(PurchaseOrder, 8301)).items_version == 1


async def test_product_id_limits_scope(db):
    await _seed_base(db)

    report = await run_backfill(db, dry_run=True, product_id=301)

    assert report.scanned == 1
    assert report.affected_po_ids == [8301]
    assert {r['po_id'] for r in report.changed + report.added + report.removed} \
        == {8301}
    # 第二产品的采购单完全未被评估/写入
    assert (await db.get(PurchaseOrder, 8302)).items_version == 0
    rows = (await db.execute(
        select(PurchaseOrderItem).where(PurchaseOrderItem.order_id == 8302)
    )).scalars().all()
    assert [float(r.quantity) for r in rows] == [10.0]


async def test_stale_part_row_removed_but_not_flagged_manual(db):
    """跨部位调整：旧行无部位、新 BOM 有部位 → 删除但不算手工行。"""
    await _seed(db, pid=303, po_id=8303, order_id=9303, product_name='产品E',
                fabric_name='绿色超柔', fabric_spec='234', fabric_unit='码',
                fabric_part='身体', fabric_supplier='美利达', old_rows=[
                    _row('绿色超柔', '234', '码', qty=50, part=None,
                         supplier='美利达', category='fabric'),
                ])

    report = await run_backfill(db, dry_run=True)

    assert len(report.removed) == 1
    assert report.removed[0]['suspected_manual'] is False
    assert len(report.added) == 1  # 新 BOM 的「身体」行


async def test_unresolved_po_reported_and_not_written(db):
    """SKU 快照名与条码均回溯不到产品 → unresolved，明细零写入。"""
    await _seed(db, pid=304, po_id=8304, order_id=9304, product_name='产品F',
                fabric_name='蓝布', fabric_spec='999', fabric_unit='码',
                fabric_supplier='供应商丙', sku_name='幽灵产品',
                source_order_ids=None, old_rows=[
                    _row('蓝布', '999', '码', qty=7, supplier='供应商丙'),
                ])

    report = await run_backfill(db, dry_run=True)

    assert [u['po_id'] for u in report.unresolved] == [8304]
    assert report.unresolved[0]['reason'] == 'unresolved_sku'
    assert report.changed == [] and report.added == [] and report.removed == []
    assert (await db.get(PurchaseOrder, 8304)).items_version == 0
    assert [q for _id, _po, _name, q in await _items(db)] == [7.0]


async def test_empty_bom_po_refused_and_not_wiped(db):
    """产品 BOM 已删空：同步服务会按空目标删光明细（Task 5 评审 Important 同款），
    校正脚本必须拒绝并报告失败，apply 也不得留下部分写入。"""
    await _seed(db, pid=305, po_id=8305, order_id=9305, product_name='产品G',
                fabric_name='旧布', fabric_spec='111', fabric_unit='码',
                fabric_supplier='供应商丁', old_rows=[
                    _row('旧布', '111', '码', qty=9, supplier='供应商丁'),
                ])
    await db.execute(delete(ProductFabric))
    await db.commit()

    report = await run_backfill(db, dry_run=False)

    assert [e['po_id'] for e in report.errors] == [8305]
    assert '空 BOM' in report.errors[0]['reason']
    assert report.changed == [] and report.added == [] and report.removed == []
    assert (await db.get(PurchaseOrder, 8305)).items_version == 0
    assert [q for _id, _po, _name, q in await _items(db)] == [9.0]
