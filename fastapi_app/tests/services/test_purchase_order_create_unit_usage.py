"""采购单生成入口必须持久化 BOM 用量（unit_usage）。

背景：`build_expected_items` 产出的行带有 `unit_usage`，但 `create_purchase_order`
此前未把它写进 `PurchaseOrderItem`，导致新生成的明细恒为 0。这会绕过
`bom_sync._inherit_fields` 的「用量未变才继承自定义数量」判定（0 ≠ 真实用量），
使手工数量在下一次 BOM 保存时被覆盖（2026-11-13 生产核查发现）。
"""
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from fastapi_app.services import purchase_order_crud as crud
from fastapi_app.shared_models import Base, PurchaseOrder, PurchaseOrderItem


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    tables = [PurchaseOrder.__table__, PurchaseOrderItem.__table__]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    maker = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


def _item(**overrides):
    row = {
        'material_name': '绿色超柔', 'specification': '234', 'unit': '码',
        'quantity': 1667, 'unit_price': 2, 'unit_usage': 1.0,
        'part_name': '身体', 'role_id': 21, 'category': 'fabric',
        'supplier_name': '美利达',
    }
    row.update(overrides)
    return row


async def _create(db, monkeypatch, items):
    async def fake_number(_db):
        return 'PO-TEST-001'

    monkeypatch.setattr(crud, 'generate_purchase_order_number', fake_number)
    return await crud.create_purchase_order(db, {
        'items': items, 'customer_name': '客户甲', 'product_name': '产品J',
        'product_quantity': 10000, 'source_order_ids': '[1]',
    })


async def test_create_purchase_order_persists_unit_usage(db, monkeypatch):
    result = await _create(db, monkeypatch, [_item()])

    item = (await db.execute(
        select(PurchaseOrderItem).where(PurchaseOrderItem.order_id == result['id'])
    )).scalars().one()
    assert float(item.unit_usage) == 1.0


async def test_create_purchase_order_manual_item_unit_usage_defaults_zero(db, monkeypatch):
    """手工/旧调用方不带 unit_usage 时保持既有默认 0，不误填。"""
    result = await _create(db, monkeypatch, [_item(unit_usage=None)])

    item = (await db.execute(
        select(PurchaseOrderItem).where(PurchaseOrderItem.order_id == result['id'])
    )).scalars().one()
    assert float(item.unit_usage) == 0.0
