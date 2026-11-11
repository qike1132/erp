"""BOM 明细同步服务测试（task-3）。

覆盖：pending 单整单重建、无变化不抖动、跨部位率/价继承、
非 pending 跳过、版本冲突 409。
"""
import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from fastapi_app.services.purchase.bom_sync import (
    ItemsVersionConflict,
    find_pending_po_ids_for_product,
    sync_pending_items_for_product,
    sync_purchase_order_items,
)
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


async def _seed(session, *, status='pending', po_id=8101, po_sku_name='产品A',
                source_order_ids='[9101]', product_barcode=None):
    """盲盒产品 201：6 角色；绿色超柔跨身体/脚底各 1.0；木棒辅料每角色 1.0。"""
    session.add(Product(id=201, name='产品A', is_blind_box=True, has_hidden_role=False,
                        barcode=product_barcode))
    for rid in range(11, 17):
        session.add(ProductRole(id=rid, product_id=201, role_name=f'角色{rid}'))
        session.add(ProductAccessory(
            id=1000 + rid, product_id=201, role_id=rid, accessory_name='木棒按摩锤',
            specification='1条', unit='个', quantity=1.0, supplier_name='木棒'))
    for fid, part in ((1, '身体'), (2, '脚底')):
        session.add(ProductFabric(
            id=fid, product_id=201, role_id=None, fabric_name='绿色超柔',
            specification='234', unit='码', quantity=1.0, part_name=part,
            supplier_name='美利达'))
    session.add(Order(id=9101, order_no='SO-9101', customer='客户甲',
                      product_id=201, quantity=10000, status='已备货'))
    session.add(OrderItem(id=1, order_id=9101, product_id=201,
                          product_name='产品A', quantity=10000))
    session.add(PurchaseOrder(
        id=po_id, order_no=f'PO-{po_id}', customer_name='客户甲', product_name='产品A',
        product_quantity=10000, supplier_name='美利达',
        source_order_ids=source_order_ids, status=status))
    session.add(PurchaseOrderSku(
        id=po_id, po_id=po_id, product_name=po_sku_name, product_barcode='bA',
        order_qty=10000, source_order_id=9101, source_record_type='order'))
    # 旧快照：绿色超柔一行 50（无部位、有率/价）；手工孤儿行 蓝色超柔 890
    session.add(PurchaseOrderItem(
        id=1, order_id=po_id, material_name='绿色超柔', specification='234',
        unit='码', part_name=None, supplier_name='美利达', quantity=50,
        loss_rate=30, unit_price=2, material_category='fabric'))
    session.add(PurchaseOrderItem(
        id=2, order_id=po_id, material_name='蓝色超柔', specification='223',
        unit='码', part_name=None, supplier_name='美利达', quantity=890,
        material_category='fabric'))
    await session.commit()


async def test_sync_rebuilds_rows_for_pending_po_blind_box(db):
    await _seed(db)
    res = await sync_purchase_order_items(db, 8101)
    assert res.changed and res.added == 8  # 绿色身体/脚底 2 行 + 6 条辅料行

    rows = (await db.execute(select(PurchaseOrderItem).where(
        PurchaseOrderItem.order_id == 8101))).scalars().all()
    green = sorted((r.part_name, float(r.quantity)) for r in rows if r.material_name == '绿色超柔')
    assert green == [('脚底', 10000.0), ('身体', 10000.0)]
    # 孤儿行（蓝色超柔）被删除
    assert all(r.material_name != '蓝色超柔' for r in rows)
    # 辅料每角色一行、合计恒等于订单量
    wood = [r for r in rows if r.material_name == '木棒按摩锤']
    assert len(wood) == 6
    assert sum(float(r.quantity) for r in wood) == 10000.0

    po = await db.get(PurchaseOrder, 8101)
    assert po.items_version == 1


async def test_sync_is_noop_when_unchanged(db):
    await _seed(db)
    await sync_purchase_order_items(db, 8101)
    res = await sync_purchase_order_items(db, 8101)
    assert res.changed is False
    po = await db.get(PurchaseOrder, 8101)
    assert po.items_version == 1  # 无变化不抖动


async def test_sync_preserves_loss_rate_and_price_across_parts(db):
    await _seed(db)
    await sync_purchase_order_items(db, 8101)
    green = (await db.execute(select(PurchaseOrderItem).where(
        PurchaseOrderItem.order_id == 8101,
        PurchaseOrderItem.material_name == '绿色超柔'))).scalars().all()
    assert {float(r.loss_rate) for r in green} == {30.0}
    assert {float(r.unit_price) for r in green} == {2.0}
    assert {float(r.total_price) for r in green} == {20600.0}  # 10000×1.03×2


async def test_sync_skips_completed_po(db):
    await _seed(db, status='completed')
    res = await sync_purchase_order_items(db, 8101)
    assert res.changed is False and res.skipped_reason == 'status:completed'


async def test_stale_version_raises_conflict(db):
    await _seed(db)
    with pytest.raises(ItemsVersionConflict):
        await sync_purchase_order_items(db, 8101, expected_version=99)


async def test_dry_run_reports_counts_without_writing(db):
    # 行锁语义（dry_run 不 FOR UPDATE）在 sqlite 无法验证（sqlite 忽略 FOR UPDATE），
    # 这里锁定 dry-run 的可观测契约：零写入、版本不变、无审计。
    await _seed(db)
    res = await sync_purchase_order_items(db, 8101, dry_run=True)
    assert res.changed and res.added == 8 and res.removed == 2
    assert sorted(res.removed_rows) == [1, 2]
    po = await db.get(PurchaseOrder, 8101)
    assert po.items_version == 0
    rows = (await db.execute(select(PurchaseOrderItem).where(
        PurchaseOrderItem.order_id == 8101))).scalars().all()
    assert len(rows) == 2  # 未删未插
    assert (await db.execute(
        select(func.count()).select_from(ModificationLog))).scalar() == 0


async def test_sync_resolves_sku_by_barcode_when_product_renamed(db):
    # 产品改名 + 无 source_order_ids：po_sku 快照名对不上，必须靠条码回退解析 pid
    await _seed(db, po_sku_name='产品A-旧名', source_order_ids=None, product_barcode='bA')
    res = await sync_purchase_order_items(db, 8101)
    assert res.changed and res.added == 8
    po = await db.get(PurchaseOrder, 8101)
    assert po.items_version == 1


async def test_sync_marks_unresolved_when_name_and_barcode_both_miss(db):
    await _seed(db, po_sku_name='不存在', source_order_ids=None)
    res = await sync_purchase_order_items(db, 8101)
    assert res.changed is False and res.skipped_reason == 'unresolved_sku'
    po = await db.get(PurchaseOrder, 8101)
    assert po.items_version == 0


async def test_sync_pending_items_for_product_batches(db):
    await _seed(db)
    matched, unresolved = await find_pending_po_ids_for_product(db, 201)
    assert matched == [8101] and unresolved == []
    out = await sync_pending_items_for_product(db, 201)
    assert out['synced'] == 1
    assert out['unresolved_po_ids'] == []
    po = await db.get(PurchaseOrder, 8101)
    assert po.items_version == 1

