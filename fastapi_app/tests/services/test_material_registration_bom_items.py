"""来料登记明细：采购明细 + BOM 补全行（明细级供应商）。

场景（生产 PO-20261107-0003）：产品 BOM 8 行（6 家供应商），采购单只落了
2 行主面料；完成采购单后登记明细应补全为 8 行，且按明细供应商分组。
"""
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from fastapi_app.services.material_registration_service import get_supplier_detail
from fastapi_app.services.purchase_order_crud import complete_purchase_order
from fastapi_app.shared_models import (
    Base,
    MaterialRegistration,
    MaterialRegistrationItem,
    ModificationLog,
    Product,
    ProductAccessory,
    ProductFabric,
    ProductMaterial,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderSku,
    PurchaseOrderStatus,
    User,
)

BOM_ROWS = [
    ('主体', '7毛精兔绒', '1214#', '码', '三虎', 0.027),
    ('肚皮', '7毛精兔绒', '1274#', '码', '三虎', 0.004),
    ('眼睛贴布', '1.0超柔', '321#', '码', '卓腾', 0.0011),
    ('头角', '1.0超柔', 'A126#', '码', '美利达', 0.0012),
    ('脚', '1.0超柔', 'A50#', '码', '美利达', 0.0039),
    ('眼镜', '2mm吉荣', 'B016#', '码', '旭日', 0.0011),
    ('眼睛包布', '本白边纶', '本白', '码', '仓库', 0.0021),
    ('嘴巴', '1.0超柔', '16#', '码', '坤成', 0.001),
]


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    tables = [
        User.__table__, Product.__table__, ProductFabric.__table__,
        ProductMaterial.__table__, ProductAccessory.__table__,
        PurchaseOrder.__table__, PurchaseOrderItem.__table__,
        PurchaseOrderSku.__table__,
        MaterialRegistration.__table__, MaterialRegistrationItem.__table__,
        ModificationLog.__table__,
    ]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    maker = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _seed(db, *, order_no: str = 'PO-TEST-0001'):
    product = Product(name='Dundun系列-猫头鹰墩挂件', barcode='6932887303032')
    db.add(product)
    await db.flush()
    for part, fabric, spec, unit, supplier, qty in BOM_ROWS:
        db.add(ProductFabric(
            product_id=product.id, part_name=part, fabric_name=fabric,
            specification=spec, unit=unit, supplier_name=supplier, quantity=qty,
        ))
    order = PurchaseOrder(
        order_no=order_no,
        supplier_name='三虎',
        customer_name='测试客户',
        product_name=product.name,
        product_quantity=10000,
        status=PurchaseOrderStatus.PENDING,
    )
    db.add(order)
    await db.flush()
    # 逐 SKU 数量快照：BOM 补全按「用量×SKU 数量」计算
    db.add(PurchaseOrderSku(
        po_id=order.id, product_name=product.name, product_barcode=product.barcode,
        order_qty=10000, source_record_type='order', source_order_id=1,
    ))
    # 采购明细只有前 2 行主面料（BOM 后补，未重新生成采购单）
    for fabric, spec in (('7毛精兔绒', '1214#'), ('7毛精兔绒', '1274#')):
        db.add(PurchaseOrderItem(
            order_id=order.id, product_name=product.name, material_name=fabric,
            specification=spec, unit='码', quantity=270 if spec == '1214#' else 40,
            supplier_name='三虎', material_category='fabric',
        ))
    await db.flush()
    return order


async def _items(db, order):
    reg = (await db.execute(
        MaterialRegistration.__table__.select().where(
            MaterialRegistration.purchase_order_id == order.id
        )
    )).mappings().one()
    rows = (await db.execute(
        MaterialRegistrationItem.__table__.select().where(
            MaterialRegistrationItem.registration_id == reg['id']
        )
    )).mappings().all()
    return reg, rows


async def test_complete_purchase_order_backfills_bom_rows_with_item_supplier(db):
    order = await _seed(db)
    await complete_purchase_order(db, order.id)

    reg, rows = await _items(db, order)
    assert reg['supplier_name'] == '三虎'
    assert len(rows) == 8, '采购明细 2 行 + BOM 补全 6 行'

    by_key = {(r['material_name'], r['specification']): r for r in rows}
    assert by_key[('7毛精兔绒', '1214#')]['supplier_name'] == '三虎'
    assert float(by_key[('7毛精兔绒', '1214#')]['ordered_quantity']) == 270
    assert by_key[('1.0超柔', '321#')]['supplier_name'] == '卓腾'
    assert float(by_key[('1.0超柔', '321#')]['ordered_quantity']) == 11
    assert by_key[('1.0超柔', 'A126#')]['supplier_name'] == '美利达'
    assert float(by_key[('1.0超柔', 'A126#')]['ordered_quantity']) == 12
    assert by_key[('1.0超柔', 'A50#')]['supplier_name'] == '美利达'
    assert float(by_key[('1.0超柔', 'A50#')]['ordered_quantity']) == 39
    assert by_key[('2mm吉荣', 'B016#')]['supplier_name'] == '旭日'
    assert by_key[('本白边纶', '本白')]['supplier_name'] == '仓库'
    assert float(by_key[('本白边纶', '本白')]['ordered_quantity']) == 21
    assert by_key[('1.0超柔', '16#')]['supplier_name'] == '坤成'
    assert float(by_key[('1.0超柔', '16#')]['ordered_quantity']) == 10
    # BOM 补全行没有采购明细关联
    assert by_key[('1.0超柔', '16#')]['order_item_id'] is None


async def test_supplier_detail_groups_by_item_supplier(db):
    order = await _seed(db, order_no='PO-TEST-0002')
    await complete_purchase_order(db, order.id)

    detail = await get_supplier_detail(db, order.order_no)
    groups = {g['supplier_name']: g for g in detail['supplier_groups']}
    assert set(groups) == {'三虎', '卓腾', '美利达', '旭日', '仓库', '坤成'}
    assert {m['name'] for m in groups['三虎']['items']} == {'7毛精兔绒'}
    assert {m['name'] for m in groups['美利达']['items']} == {'1.0超柔'}
    assert len(groups['美利达']['items'][0]['sub_items']) == 2
