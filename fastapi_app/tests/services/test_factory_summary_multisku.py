"""多 SKU 采购单的「汇总下单」口径回归测试。

背景（用户报告 BUG，2026-09-18）：
    客户订单 68756（奥飞，4 个 SKU 各 999,111）经汇总下单生成采购单 20404 后，
    弹窗「产品名称」只显示 **1 个 SKU**（妹妹二代），其余 3 个 SKU 的名称与物料
    全部消失。

根因（两层，均读「兼容字段」而非 SKU 明细）：
    1. `services/purchase/_factory._fetch_factory_cust_order_map` 读
       `Order.product_id`（= **首个** SKU）与 `Order.quantity`（= 所有 SKU 之和），
       `_resolve_factory_po_info` 再用该 pid 的产品名**覆盖**采购单主表
       `product_name`（主表里明明是 4 个名称的 '、' 拼接串）→ 只显示 1 个 SKU。
    2. `_build_factory_group_map` / `_build_supplier_mat_map` 只对首个 SKU 的
       BOM 展开 → 其余 SKU 的物料**不进汇总**（漏料），而打印/导出同源于该结果。

本文件锁定修复后的契约：
    C1  产品名称 = 采购单主表值（多 SKU 时为完整清单），不得被首个 SKU 覆盖；
    C2  物料集合 = 该采购单**全部 SKU** BOM 的并集（不再只首个 SKU）；
    C3  跨 SKU 重复的同一物料**只能计一次**（数量取自跨 SKU 合并后的采购单明细，
        重复累加会使数量翻倍）；
    C4  单 SKU 采购单行为与修复前逐字一致（零回归）。
"""
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from fastapi_app.services.purchase_order_query import (
    get_factory_order_summary,
    get_supplier_order_summary,
)
from fastapi_app.shared_models import (
    Base,
    Order,
    OrderItem,
    Product,
    ProductAccessory,
    ProductFabric,
    ProductMaterial,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderSku,
)

SHARED = '共享布'      # 两个 SKU 的 BOM 都用到（验证 C3，不可翻倍）
ONLY_A = 'A专有布'     # 仅 SKU-A 用到（验证 C2，修复前缺失）
ONLY_B = 'B专有布'     # 仅 SKU-B 用到（验证 C2，修复前缺失）


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    statements: list[str] = []

    @event.listens_for(engine.sync_engine, 'before_cursor_execute')
    def _record_sql(_conn, _cursor, statement, _params, _context, _many):  # pragma: no cover
        statements.append(statement)

    tables = [
        PurchaseOrder.__table__, PurchaseOrderItem.__table__, PurchaseOrderSku.__table__,
        Order.__table__, OrderItem.__table__, Product.__table__,
        ProductFabric.__table__, ProductAccessory.__table__, ProductMaterial.__table__,
    ]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    maker = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session, statements
    await engine.dispose()


async def _seed_single_or_multi(db: AsyncSession, *, multi: bool) -> int:
    """构造 1 张客户订单（1 或 2 个 SKU）+ 1 张采购单，返回采购单 id。

    产品 A / B 的 BOM 同时包含 SHARED，用于验证跨 SKU 去重。
    采购单明细数量 = 「跨 SKU 合并后的总采购量」——
    共享布 60（A+B 合计），A专有布 20，B专有布 40。
    """
    db.add(Product(id=101, name='产品A'))
    db.add(Product(id=102, name='产品B'))
    db.add(ProductFabric(id=1, product_id=101, fabric_name=SHARED, specification='S1', unit='米', quantity=0.2, supplier_name='供应商甲'))
    db.add(ProductFabric(id=2, product_id=101, fabric_name=ONLY_A, specification='S2', unit='米', quantity=0.2, supplier_name='供应商甲'))
    db.add(ProductFabric(id=3, product_id=102, fabric_name=SHARED, specification='S1', unit='米', quantity=0.2, supplier_name='供应商甲'))
    db.add(ProductFabric(id=4, product_id=102, fabric_name=ONLY_B, specification='S3', unit='米', quantity=0.2, supplier_name='供应商甲'))

    # 客户订单：product_id / quantity 为兼容字段（首个 SKU + 全部之和）
    db.add(Order(
        id=9001, order_no='SO-9001', customer='客户甲',
        product_id=101, quantity=300 if multi else 100, status='待备货',
    ))
    db.add(OrderItem(id=1, order_id=9001, product_id=101, product_name='产品A', quantity=100))
    if multi:
        db.add(OrderItem(id=2, order_id=9001, product_id=102, product_name='产品B', quantity=200))

    db.add(PurchaseOrder(
        id=8001, order_no='PO-8001', customer_name='客户甲',
        # 主表权威值：多 SKU 时为 '、' 拼接的完整清单
        product_name='产品A、产品B' if multi else '产品A',
        product_quantity=300 if multi else 100,
        supplier_name='供应商甲', source_order_ids='[9001]',
    ))
    db.add(PurchaseOrderItem(id=1, order_id=8001, material_name=SHARED, specification='S1', unit='米', quantity=60, supplier_name='供应商甲'))
    if multi:
        db.add(PurchaseOrderItem(id=2, order_id=8001, material_name=ONLY_A, specification='S2', unit='米', quantity=20, supplier_name='供应商甲'))
        db.add(PurchaseOrderItem(id=3, order_id=8001, material_name=ONLY_B, specification='S3', unit='米', quantity=40, supplier_name='供应商甲'))
    else:
        db.add(PurchaseOrderItem(id=2, order_id=8001, material_name=ONLY_A, specification='S2', unit='米', quantity=20, supplier_name='供应商甲'))
    await db.commit()
    return 8001


def _fabrics(group) -> dict[str, float]:
    out: dict[str, float] = {}
    for supplier in group['suppliers']:
        for fabric in supplier['fabrics']:
            out[fabric['fabric_name']] = float(fabric['quantity'])
    return out


async def test_c1_multisku_po_shows_all_sku_names(db):
    """C1：多 SKU 采购单的产品名称必须是完整清单，不得被首个 SKU 覆盖。"""
    session, _ = db
    po_id = await _seed_single_or_multi(session, multi=True)

    result = await get_factory_order_summary(session, [po_id])

    assert len(result['groups']) == 1
    assert result['groups'][0]['product_name'] == '产品A、产品B'


async def test_c2_multisku_po_includes_every_sku_bom(db):
    """C2：物料集合必须是全部 SKU BOM 的并集（修复前只有首个 SKU 的物料）。"""
    session, _ = db
    po_id = await _seed_single_or_multi(session, multi=True)

    fabrics = _fabrics((await get_factory_order_summary(session, [po_id]))['groups'][0])

    assert set(fabrics) == {SHARED, ONLY_A, ONLY_B}


async def test_c3_shared_material_counted_once(db):
    """C3：跨 SKU 重复的物料只能计一次（数量 = 采购单明细值，不得翻倍）。"""
    session, _ = db
    po_id = await _seed_single_or_multi(session, multi=True)

    fabrics = _fabrics((await get_factory_order_summary(session, [po_id]))['groups'][0])

    assert fabrics[SHARED] == 60

    materials = {
        m['material_name']: m['total_quantity']
        for m in (await get_supplier_order_summary(session, [po_id]))['materials']
    }
    assert materials[SHARED] == 60
    assert materials[ONLY_A] == 20
    assert materials[ONLY_B] == 40


async def test_c4_single_sku_unchanged(db):
    """C4：单 SKU 采购单与修复前逐字一致（零回归）。"""
    session, _ = db
    po_id = await _seed_single_or_multi(session, multi=False)

    group = (await get_factory_order_summary(session, [po_id]))['groups'][0]

    assert group['product_name'] == '产品A'
    assert group['product_quantity'] == 100
    assert _fabrics(group) == {SHARED: 60, ONLY_A: 20}


# ===== skus[]：前端「逐 SKU 分行」的数据来源 =====

async def test_c5_skus_from_snapshot(db):
    """C5：有逐 SKU 快照时，skus[] 取快照（权威），且 Σorder_qty == product_quantity。"""
    session, _ = db
    po_id = await _seed_single_or_multi(session, multi=True)
    session.add_all([
        PurchaseOrderSku(id=1, po_id=po_id, product_name='产品A', product_barcode='bA',
                         order_qty=100, source_order_id=9001, source_record_type='order'),
        PurchaseOrderSku(id=2, po_id=po_id, product_name='产品B', product_barcode='bB',
                         order_qty=200, source_order_id=9001, source_record_type='order'),
    ])
    await session.commit()

    group = (await get_factory_order_summary(session, [po_id]))['groups'][0]

    assert [s['product_name'] for s in group['skus']] == ['产品A', '产品B']
    assert [float(s['order_qty']) for s in group['skus']] == [100, 200]
    assert sum(float(s['order_qty']) for s in group['skus']) == group['product_quantity']


async def test_c6_skus_fallback_when_snapshot_empty(db):
    """C6：无逐 SKU 快照（迁移前生成 / 未回填）→ 回退 OrderItem 口径，绝不空手。"""
    session, _ = db
    po_id = await _seed_single_or_multi(session, multi=True)   # 不写 purchase_order_sku

    group = (await get_factory_order_summary(session, [po_id]))['groups'][0]

    assert [s['product_name'] for s in group['skus']] == ['产品A', '产品B']
    assert [float(s['order_qty']) for s in group['skus']] == [100, 200]


async def test_c7_skus_single_line_for_single_sku(db):
    """C7：单 SKU 采购单 skus[] 只有一行 —— 前端据此不渲染「合计」子行（零回归）。"""
    session, _ = db
    po_id = await _seed_single_or_multi(session, multi=False)

    group = (await get_factory_order_summary(session, [po_id]))['groups'][0]

    assert len(group['skus']) == 1
    assert group['skus'][0]['product_name'] == '产品A'
    assert float(group['skus'][0]['order_qty']) == 100
