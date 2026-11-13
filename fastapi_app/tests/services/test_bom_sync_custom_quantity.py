"""pending 采购单「自定义数量」在 BOM 保存重建后的保留（2026-11-13 口径）。

业务规则：
- 自定义数量只对当前这张 PO 有效，不写 BOM、不跨单、不影响其他客户/角色；
- BOM 保存触发 pending 单整单重建时，按（角色,物料,规格,单位,部位,供应商,类别）
  精确键继承该行数量（范围仅该 SKU + 该角色 + 该部位，不做跨部位回退）；
- 该行 BOM 用量本身变了 → BOM 优先重算（2026-11-11 实时同步裁决：BOM 是唯一真源）；
- completed 单是快照，同步永不改写；新 PO 仍按 BOM 用量 × 订单数量重算。
"""
from decimal import Decimal

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from fastapi_app.services.purchase.bom_sync import sync_purchase_order_items
from fastapi_app.services.purchase_order_crud import complete_purchase_order
from fastapi_app.services.purchase_order_generate import (
    _load_bom_context,
    build_expected_items,
)
from fastapi_app.shared_models import (
    Base,
    MaterialRegistration,
    MaterialRegistrationItem,
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


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    tables = [PurchaseOrder.__table__, PurchaseOrderItem.__table__, PurchaseOrderSku.__table__,
              Order.__table__, OrderItem.__table__, Product.__table__,
              ProductFabric.__table__, ProductAccessory.__table__, ProductRole.__table__,
              ProductMaterial.__table__, ModificationLog.__table__,
              MaterialRegistration.__table__, MaterialRegistrationItem.__table__]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    maker = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _seed(session, *, status: str = 'pending', quantity: float = 10000):
    """单角色产品 208：绿色超柔（身体，1.0 码/件）+ 一张 PO（默认 qty=10000）。

    PO 明细行是「按 BOM 生成」的形态：unit_usage 与 BOM 当前用量一致。
    """
    session.add(Product(id=208, name='产品J', is_blind_box=False,
                        has_hidden_role=False))
    session.add(ProductFabric(
        id=20801, product_id=208, role_id=None, fabric_name='绿色超柔',
        specification='234', unit='码', quantity=1.0, part_name='身体',
        supplier_name='美利达'))
    session.add(Order(id=9208, order_no='SO-9208', customer='客户甲',
                      product_id=208, quantity=10000, status='已备货'))
    session.add(OrderItem(id=92081, order_id=9208, product_id=208,
                          product_name='产品J', quantity=10000))
    session.add(PurchaseOrder(
        id=8501, order_no='PO-8501', customer_name='客户甲', product_name='产品J',
        product_quantity=10000, supplier_name='美利达',
        source_order_ids='[9208]', status=status))
    session.add(PurchaseOrderSku(
        id=8501, po_id=8501, product_name='产品J', product_barcode='',
        order_qty=10000, source_order_id=9208, source_record_type='order'))
    session.add(PurchaseOrderItem(
        id=8521, order_id=8501, material_name='绿色超柔', specification='234',
        unit='码', part_name='身体', supplier_name='美利达',
        material_category='fabric', quantity=quantity, unit_usage=1.0))
    await session.commit()


async def _quantities(db, po_id: int = 8501) -> list[float]:
    rows = (await db.execute(
        select(PurchaseOrderItem)
        .where(PurchaseOrderItem.order_id == po_id)
        .order_by(PurchaseOrderItem.id)
    )).scalars().all()
    return [float(r.quantity) for r in rows]


async def test_custom_quantity_survives_pending_resync(db):
    """手工把 10000 改成 20000 后，BOM 保存触发的重建不得把它改回去。

    修复前：_inherit_fields 只继承 loss_rate/unit_price/remark，目标行数量
    按 BOM 重算为 10000 → 整单重建后自定义值丢失。修复后：精确键 + 该行
    BOM 用量未变 → 继承 20000；规范序列一致，连重建都不发生。
    """
    await _seed(db)
    row = await db.get(PurchaseOrderItem, 8521)
    row.quantity = Decimal('20000')
    await db.commit()

    res = await sync_purchase_order_items(db, 8501)

    assert await _quantities(db) == [20000.0], '自定义数量在 BOM 重建后丢失'
    assert res.changed is False, 'BOM 未变，自定义数量应使同步短路（不重建、不递增版本）'
    assert (await db.get(PurchaseOrder, 8501)).items_version == 0


async def test_custom_quantity_kept_on_completed_snapshot(db):
    """completed 单是快照：同步直接跳过，20000 原样保留。"""
    await _seed(db, status='completed')
    row = await db.get(PurchaseOrderItem, 8521)
    row.quantity = Decimal('20000')
    await db.commit()

    res = await sync_purchase_order_items(db, 8501)

    assert res.changed is False and res.skipped_reason == 'status:completed'
    assert await _quantities(db) == [20000.0]


async def test_new_po_quantity_still_computed_from_bom(db):
    """新 PO 仍按 BOM：1.0 码/件 × 10000 件 = 10000（自定义值不回流 BOM）。"""
    await _seed(db)

    ctx = await _load_bom_context(db, [208])
    target = build_expected_items(
        [{'product_name': '产品J', 'order_qty': 10000}], ctx, {'产品J': 208}, '客户甲',
    )

    assert [float(t['quantity']) for t in target] == [10000.0]
    fabric = (await db.execute(select(ProductFabric))).scalars().one()
    assert float(fabric.quantity) == 1.0, '自定义数量不得回写 BOM 用量'


async def test_bom_usage_change_overrides_custom_quantity(db):
    """该行 BOM 用量真变了 → BOM 优先重算（实时同步的存在意义，PO-2611 事故）。

    无留底字段可区分「手工调整」与「旧 BOM 快照」，故继承只在该行用量未变时
    生效：用量变了说明需求变了，继续保留旧数量会让 BOM 修改对 pending 单失效。
    """
    await _seed(db)
    row = await db.get(PurchaseOrderItem, 8521)
    row.quantity = Decimal('20000')
    fabric = await db.get(ProductFabric, 20801)
    fabric.quantity = 1.5
    await db.commit()

    res = await sync_purchase_order_items(db, 8501)

    assert res.changed is True
    assert await _quantities(db) == [15000.0]
    rebuilt = (await db.execute(
        select(PurchaseOrderItem).where(PurchaseOrderItem.order_id == 8501)
    )).scalars().one()
    assert float(rebuilt.unit_usage) == 1.5


async def test_custom_quantity_survives_full_rebuild_from_other_bom_change(db):
    """BOM 新增其它物料 → 整单重建（非短路），自定义行数量仍继承 20000。"""
    await _seed(db)
    row = await db.get(PurchaseOrderItem, 8521)
    row.quantity = Decimal('20000')
    db.add(ProductAccessory(
        id=20802, product_id=208, role_id=None, accessory_name='木棒',
        specification='1条', unit='个', quantity=1.0, supplier_name='木棒'))
    await db.commit()

    res = await sync_purchase_order_items(db, 8501)

    assert res.changed is True and res.added == 1
    rows = (await db.execute(
        select(PurchaseOrderItem).where(PurchaseOrderItem.order_id == 8501)
    )).scalars().all()
    by_name = {r.material_name: float(r.quantity) for r in rows}
    assert by_name == {'绿色超柔': 20000.0, '木棒': 10000.0}


async def test_custom_quantity_not_smeared_across_parts(db):
    """只继承同部位行：身体 20000 不得覆盖脚底（范围仅该 SKU + 角色 + 部位）。"""
    await _seed(db)
    db.add(ProductFabric(
        id=20812, product_id=208, role_id=None, fabric_name='绿色超柔',
        specification='234', unit='码', quantity=1.0, part_name='脚底',
        supplier_name='美利达'))
    db.add(PurchaseOrderItem(
        id=8522, order_id=8501, material_name='绿色超柔', specification='234',
        unit='码', part_name='脚底', supplier_name='美利达',
        material_category='fabric', quantity=10000, unit_usage=1.0))
    await db.commit()
    body = await db.get(PurchaseOrderItem, 8521)
    body.quantity = Decimal('20000')
    await db.commit()

    await sync_purchase_order_items(db, 8501)

    rows = (await db.execute(
        select(PurchaseOrderItem).where(PurchaseOrderItem.order_id == 8501)
    )).scalars().all()
    by_part = {r.part_name: float(r.quantity) for r in rows}
    assert by_part == {'身体': 20000.0, '脚底': 10000.0}


async def _seed_role_po(session):
    """产品 209：香珠在角色 11/12 各一行，PO 8502 对应两行各 1000。"""
    session.add(Product(id=209, name='产品K', is_blind_box=False,
                        has_hidden_role=False))
    for rid in (11, 12):
        session.add(ProductRole(id=rid, product_id=209, role_name=f'角色{rid}'))
        session.add(ProductAccessory(
            id=20900 + rid, product_id=209, role_id=rid, accessory_name='香珠',
            specification='5g', unit='个', quantity=1.0, supplier_name='香味'))
    session.add(Order(id=9209, order_no='SO-9209', customer='客户乙',
                      product_id=209, quantity=1000, status='已备货'))
    session.add(OrderItem(id=92091, order_id=9209, product_id=209,
                          product_name='产品K', quantity=1000))
    session.add(PurchaseOrder(
        id=8502, order_no='PO-8502', customer_name='客户乙', product_name='产品K',
        product_quantity=1000, supplier_name='香味',
        source_order_ids='[9209]', status='pending'))
    session.add(PurchaseOrderSku(
        id=8502, po_id=8502, product_name='产品K', product_barcode='',
        order_qty=1000, source_order_id=9209, source_record_type='order'))
    for item_id, rid in ((8531, 11), (8532, 12)):
        session.add(PurchaseOrderItem(
            id=item_id, order_id=8502, role_id=rid, material_name='香珠',
            specification='5g', unit='个', part_name=None, supplier_name='香味',
            material_category='accessory', quantity=1000, unit_usage=1.0))
    await session.commit()


async def test_custom_quantity_not_smeared_across_roles(db):
    """只继承同角色行：角色 11 的 2000 不得覆盖角色 12 的 1000。"""
    await _seed_role_po(db)
    row = await db.get(PurchaseOrderItem, 8531)
    row.quantity = Decimal('2000')
    await db.commit()

    await sync_purchase_order_items(db, 8502)

    rows = (await db.execute(
        select(PurchaseOrderItem).where(
            PurchaseOrderItem.order_id == 8502,
            PurchaseOrderItem.material_name == '香珠',
        )
    )).scalars().all()
    by_role = {r.role_id: float(r.quantity) for r in rows}
    assert by_role == {11: 2000.0, 12: 1000.0}


async def test_force_quantity_rebuild_ignores_custom_quantity(db):
    """盲盒配置变更等场景强制重算：即使 unit_usage 未变也不继承旧数量。

    旧数量是上一套角色分配的结果，不是用户手工值；强制模式下必须按 BOM 重算。
    损耗率/单价/备注仍按原口径继承（只关闭数量继承）。
    """
    await _seed(db)
    row = await db.get(PurchaseOrderItem, 8521)
    row.quantity = Decimal('20000')
    row.loss_rate = Decimal('30')
    row.unit_price = Decimal('2')
    await db.commit()

    res = await sync_purchase_order_items(db, 8501, force_quantity_from_bom=True)

    assert res.changed is True
    rebuilt = (await db.execute(
        select(PurchaseOrderItem).where(PurchaseOrderItem.order_id == 8501)
    )).scalars().one()
    assert float(rebuilt.quantity) == 10000.0
    assert float(rebuilt.loss_rate) == 30.0
    assert float(rebuilt.unit_price) == 2.0


async def test_manual_verification_sequence(db):
    """手工验证全链路：自定义 20000 → BOM 保存同步 → 仍 20000 → 完成下单
    → 完成单仍 20000 → 新 PO 为 10000。"""
    await _seed(db)
    row = await db.get(PurchaseOrderItem, 8521)
    row.quantity = Decimal('20000')
    await db.commit()

    # 1) BOM 保存触发重建（无 BOM 变化）
    await sync_purchase_order_items(db, 8501)
    assert await _quantities(db) == [20000.0]

    # 2) 走到下单完成（真实完成服务，而非只改状态字段）
    result = await complete_purchase_order(db, 8501, 'tester')
    await db.commit()
    assert result['status'] == 'completed'
    assert await _quantities(db) == [20000.0]

    # 3) 完成后再保存 BOM：同步跳过 completed 单
    res = await sync_purchase_order_items(db, 8501)
    assert res.changed is False and res.skipped_reason == 'status:completed'
    assert await _quantities(db) == [20000.0]

    # 4) 后续新 PO 仍按 BOM 用量 × 订单数量 = 10000
    ctx = await _load_bom_context(db, [208])
    target = build_expected_items(
        [{'product_name': '产品J', 'order_qty': 10000}], ctx, {'产品J': 208}, '客户甲',
    )
    assert [float(t['quantity']) for t in target] == [10000.0]
