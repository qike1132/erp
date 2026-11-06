"""工厂内部订单「产品部位」拆行 / 旧单回退回归测试。

需求：同一物料用于多个部位时，工厂汇总按部位拆行；旧采购明细没有 part_name 时
按物料合并，绝不重复计量或让两行共用同一 item_ids。
"""
from types import SimpleNamespace

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from fastapi_app.services.purchase_order_generate import _material_row
from fastapi_app.services.purchase_order_query import get_factory_order_summary
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

MATERIAL = '面料A'
SPEC = 'S1'
UNIT = '米'


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    tables = [
        PurchaseOrder.__table__, PurchaseOrderItem.__table__, PurchaseOrderSku.__table__,
        Order.__table__, OrderItem.__table__, Product.__table__,
        ProductFabric.__table__, ProductAccessory.__table__, ProductMaterial.__table__,
    ]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    maker = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _seed(
    db: AsyncSession,
    *,
    po_id: int = 8001,
    item_parts: tuple[str | None, str | None] = ('身体', '头部'),
    bom_parts: tuple[str | None, str | None] = ('身体', '头部'),
    quantities: tuple[float, float] = (12, 8),
    order_id: int = 9001,
    order_item_id: int = 1,
    sku_id: int = 1,
    with_product: bool = True,
) -> int:
    """一个产品、两条同物料不同部位的 BOM 行 + 一条采购单。

    用量 0.12 / 0.08 × 订单 100 = 12 / 8，与落库明细一致。
    """
    if with_product:
        db.add(Product(id=101, name='产品A'))
    db.add(ProductFabric(
        id=po_id * 10 + 1, product_id=101, fabric_name=MATERIAL, specification=SPEC, unit=UNIT,
        quantity=0.12, supplier_name='供应商甲', part_name=bom_parts[0],
    ))
    db.add(ProductFabric(
        id=po_id * 10 + 2, product_id=101, fabric_name=MATERIAL, specification=SPEC, unit=UNIT,
        quantity=0.08, supplier_name='供应商甲', part_name=bom_parts[1],
    ))
    db.add(Order(id=order_id, order_no=f'SO-{order_id}', customer='客户甲',
                 product_id=101, quantity=100, status='待备货'))
    db.add(OrderItem(id=order_item_id, order_id=order_id, product_id=101,
                     product_name='产品A', quantity=100))
    db.add(PurchaseOrder(
        id=po_id, order_no=f'PO-{po_id}', customer_name='客户甲', product_name='产品A',
        product_quantity=100, supplier_name='供应商甲', source_order_ids=f'[{order_id}]',
    ))
    db.add(PurchaseOrderItem(
        id=po_id * 10 + 1, order_id=po_id, material_name=MATERIAL, specification=SPEC,
        unit=UNIT, quantity=quantities[0], supplier_name='供应商甲', part_name=item_parts[0],
    ))
    db.add(PurchaseOrderItem(
        id=po_id * 10 + 2, order_id=po_id, material_name=MATERIAL, specification=SPEC,
        unit=UNIT, quantity=quantities[1], supplier_name='供应商甲', part_name=item_parts[1],
    ))
    db.add(PurchaseOrderSku(
        id=sku_id, po_id=po_id, product_name='产品A', product_barcode='bA',
        order_qty=100, source_order_id=order_id, source_record_type='order',
    ))
    await db.commit()
    return po_id


def _fabrics(group) -> list[dict]:
    return [f for sup in group['suppliers'] for f in sup['fabrics']]


async def test_new_order_splits_same_material_by_part(db):
    """新单：同物料两个部位 → 两条 fabric 行，item_ids 不重叠，数量各取落库值。"""
    session = db
    po_id = await _seed(session)

    group = (await get_factory_order_summary(session, [po_id]))['groups'][0]
    fabrics = _fabrics(group)

    by_part = {f.get('part_name'): f for f in fabrics}
    assert set(by_part) == {'身体', '头部'}
    assert float(by_part['身体']['quantity']) == 12
    assert float(by_part['头部']['quantity']) == 8
    assert list(by_part['身体']['item_ids']) == [po_id * 10 + 1]
    assert list(by_part['头部']['item_ids']) == [po_id * 10 + 2]
    assert set(by_part['身体']['item_ids']).isdisjoint(by_part['头部']['item_ids'])

    # 按 SKU 展开的物料也按部位两行
    sku_materials = group['skus'][0]['materials']
    by_part_sku = {m.get('part_name'): m for m in sku_materials}
    assert set(by_part_sku) == {'身体', '头部'}
    assert float(by_part_sku['身体']['quantity']) == 12
    assert float(by_part_sku['头部']['quantity']) == 8


async def test_legacy_order_without_item_part_names_stays_merged(db):
    """旧单：采购明细无 part_name，即使 BOM 有部位也按物料合并，且只计一次落库量。"""
    session = db
    po_id = await _seed(session, item_parts=(None, None))

    group = (await get_factory_order_summary(session, [po_id]))['groups'][0]
    fabrics = _fabrics(group)

    assert len(fabrics) == 1
    assert not fabrics[0].get('part_name')
    assert float(fabrics[0]['quantity']) == 20, '落库两行合计只能计一次，不得翻倍'

    sku_materials = group['skus'][0]['materials']
    assert len(sku_materials) == 1
    assert not sku_materials[0].get('part_name')
    assert float(sku_materials[0]['quantity']) == 20


async def test_mixed_group_falls_back_to_merged(db):
    """混合组：组内任一旧单即整组按物料合并，避免部分拆分/重复计量。"""
    session = db
    await _seed(session, po_id=8001)
    await _seed(
        session, po_id=8002, item_parts=(None, None), quantities=(5, 5),
        order_id=9002, order_item_id=2, sku_id=2, with_product=False,
    )

    group = (await get_factory_order_summary(session, [8001, 8002]))['groups'][0]
    fabrics = _fabrics(group)

    assert len(fabrics) == 1
    assert not fabrics[0].get('part_name')
    assert float(fabrics[0]['quantity']) == 30, '8001 的 12+8 与 8002 的 5+5 各计一次'


def test_material_row_carries_part_name():
    """生成采购明细的 dict 必须携带 BOM 行的 part_name。"""
    spec = SimpleNamespace(
        usage_attr='quantity', name_attr='fabric_name', default_name='面料',
        default_unit='米', category='fabric',
    )
    row = SimpleNamespace(
        fabric_name=MATERIAL,
        quantity=0.12, material_code='M1', specification=SPEC, unit=UNIT,
        supplier_name='供应商甲', supplier_id=1, part_name='身体',
    )

    result = _material_row(spec, row, 100, '产品A', '客户甲', '默认BOM')

    assert result['part_name'] == '身体'
    assert result['quantity'] == 12


def test_backend_factory_print_has_part_column():
    """后端工厂汇总打印同步 8 列：表头与行都带产品部位。"""
    from fastapi_app.api.v1.endpoints.purchase_center.export_utils import (
        generate_factory_summary_print,
    )

    order = SimpleNamespace(
        id=1, order_no='PO-1', source_order_id=None, product_name='产品A',
        product_quantity=100, customer_name='客户甲', supplier_name='供应商甲',
    )
    item = SimpleNamespace(
        material_name=MATERIAL, specification=SPEC, unit=UNIT, quantity=12,
        supplier_name='供应商甲', part_name='身体',
    )

    html = generate_factory_summary_print([order], {1: [item]})

    assert '<th>产品部位</th>' in html
    assert '<td style="text-align:left">身体</td>' in html


async def test_po_with_mixed_part_and_null_items_merges(db):
    """一张 PO 内混有带部位与无部位明细 → 整组按物料合并，空部位明细不得被丢弃。"""
    session = db
    po_id = await _seed(session, item_parts=('身体', None), bom_parts=('身体', None))

    group = (await get_factory_order_summary(session, [po_id]))['groups'][0]
    fabrics = _fabrics(group)

    assert len(fabrics) == 1
    assert not fabrics[0].get('part_name')
    assert float(fabrics[0]['quantity']) == 20, '12 + 8 必须都计入，不得丢空部位明细'


def test_backend_factory_print_mixed_parts_merges():
    """后端打印与屏幕同口径：PO 内混有无部位明细时按物料合并，不拆两行。"""
    from fastapi_app.api.v1.endpoints.purchase_center.export_utils import (
        generate_factory_summary_print,
    )

    order = SimpleNamespace(
        id=1, order_no='PO-1', source_order_id=None, product_name='产品A',
        product_quantity=100, customer_name='客户甲', supplier_name='供应商甲',
    )
    items = [
        SimpleNamespace(
            material_name=MATERIAL, specification=SPEC, unit=UNIT, quantity=12,
            supplier_name='供应商甲', part_name='身体',
        ),
        SimpleNamespace(
            material_name=MATERIAL, specification=SPEC, unit=UNIT, quantity=8,
            supplier_name='供应商甲', part_name=None,
        ),
    ]

    html = generate_factory_summary_print([order], {1: items})

    assert '<th>产品部位</th>' in html
    assert html.count('<td style="text-align:left"></td>') == 1
    assert '>20.0 米<' in html
