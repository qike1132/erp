"""BOM「产品部位」part_name：请求归一、三表落库/读回、复制携带。

覆盖用户需求：
- 保存请求的 part_name 前后空白 trim，空串存 NULL，超长拒绝；
- product_fabric / product_material / product_accessory 三张表分别生效；
- BOM 查询（get_bom）与复制预览返回 part_name；
- 复制 BOM（产品级默认路径与目标角色路径）一并复制 part_name。

用内存 SQLite 真实 session；不触碰生产库。
"""
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from fastapi_app.schemas.purchase_center import (
    AccessoryItem,
    BomSaveRequest,
    FabricItem,
    FillingItem,
)
from fastapi_app.services import bom_service, purchase_bom_copy_service
from fastapi_app.shared_models import Base, Role
from fastapi_app.shared_models.product import Product
from fastapi_app.shared_models.product_material import (
    ProductAccessory,
    ProductFabric,
    ProductMaterial,
    ProductRole,
)

# 仅建测试路径会用到的表；Supplier 用空 supplier_name 绕开（resolve_bom_suppliers 直接返回 {}）。
_TABLES = [
    Role.__table__,
    Product.__table__,
    ProductRole.__table__,
    ProductFabric.__table__,
    ProductAccessory.__table__,
    ProductMaterial.__table__,
]


@pytest.fixture
async def db_session():
    engine = create_async_engine(
        'sqlite+aiosqlite:///:memory:',
        poolclass=StaticPool,
        connect_args={'check_same_thread': False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=_TABLES))
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


def _save_payload() -> dict:
    return {
        'fabrics': [{
            'fabric_name': '面料A', 'specification': 'S', 'unit': '码',
            'quantity': 1, 'supplier_name': '', 'part_name': '  身体  ',
        }],
        'accessories': [{
            'accessory_name': '拉链', 'specification': 'S', 'unit': '个',
            'quantity': 1, 'supplier_name': '', 'part_name': '头部',
        }],
        'fillings': [{
            'cotton_usage': 10, 'specification': 'S', 'unit': '克',
            'supplier_name': '', 'part_name': '   ',
        }],
    }


async def _seed_product(db, product_id: int = 1) -> None:
    db.add(Product(id=product_id, name=f'产品{product_id}', price=1))
    await db.commit()


async def _seed_source_with_parts(db) -> None:
    """源产品默认作用域三表各一行，均带 part_name；目标产品为空。"""
    db.add_all([
        Product(id=1, name='部位源产品', price=1),
        Product(id=2, name='部位目标产品', price=1),
    ])
    await db.flush()
    db.add_all([
        ProductMaterial(
            product_id=1, role_id=None, part_name='躯干',
            cotton_usage=Decimal('12'), unit='克',
        ),
        ProductFabric(
            product_id=1, role_id=None, part_name='身体',
            fabric_name='面料A', quantity=Decimal('1'), unit='码',
        ),
        ProductAccessory(
            product_id=1, role_id=None, part_name='头部',
            accessory_name='拉链', quantity=Decimal('1'), unit='个',
        ),
    ])
    await db.commit()


# ===== 请求 schema =====

def test_schema_trims_part_name_and_blank_becomes_none():
    req = BomSaveRequest.model_validate(_save_payload())
    assert req.fabrics[0].part_name == '身体'
    assert req.accessories[0].part_name == '头部'
    assert req.fillings[0].part_name is None


def test_schema_rejects_part_name_over_100_after_trim():
    with pytest.raises(ValidationError):
        FabricItem(fabric_name='布', part_name='甲' * 101)

    # 先 trim 再校验长度：前后空白不占 100 字额度
    at_limit = FabricItem(fabric_name='布', part_name=' ' + '甲' * 100 + ' ')
    assert at_limit.part_name == '甲' * 100


def test_schema_part_name_optional_for_all_three_items():
    assert FabricItem(fabric_name='布').part_name is None
    assert AccessoryItem(accessory_name='拉链').part_name is None
    assert FillingItem(cotton_usage=1).part_name is None


# ===== 保存落库 / 读回 =====

async def test_save_bom_persists_part_name_to_three_tables(db_session):
    db = db_session
    await _seed_product(db)

    await bom_service.save_bom(db, 1, _save_payload(), 'tester')
    await db.flush()

    fabric = (await db.execute(
        select(ProductFabric).where(ProductFabric.product_id == 1)
    )).scalar_one()
    accessory = (await db.execute(
        select(ProductAccessory).where(ProductAccessory.product_id == 1)
    )).scalar_one()
    material = (await db.execute(
        select(ProductMaterial).where(ProductMaterial.product_id == 1)
    )).scalar_one()

    assert fabric.part_name == '身体'       # 前后空白被 trim
    assert accessory.part_name == '头部'
    assert material.part_name is None       # 纯空白 → NULL


async def test_save_bom_can_update_existing_part_name(db_session):
    db = db_session
    await _seed_product(db)
    await bom_service.save_bom(db, 1, _save_payload(), 'tester')
    await db.flush()

    fabric = (await db.execute(
        select(ProductFabric).where(ProductFabric.product_id == 1)
    )).scalar_one()
    accessory = (await db.execute(
        select(ProductAccessory).where(ProductAccessory.product_id == 1)
    )).scalar_one()
    material = (await db.execute(
        select(ProductMaterial).where(ProductMaterial.product_id == 1)
    )).scalar_one()

    updated = _save_payload()
    updated['fabrics'][0].update({'id': fabric.id, 'part_name': '腿部'})
    updated['accessories'][0].update({'id': accessory.id, 'part_name': '手部'})
    updated['fillings'][0].update({'id': material.id, 'part_name': '腰部'})

    await bom_service.save_bom(db, 1, updated, 'tester')
    await db.flush()

    assert fabric.part_name == '腿部'
    assert accessory.part_name == '手部'
    assert material.part_name == '腰部'


async def test_get_bom_returns_part_name(db_session):
    db = db_session
    await _seed_product(db)
    await bom_service.save_bom(db, 1, _save_payload(), 'tester')
    await db.flush()

    result = await bom_service.get_bom(db, 1)
    assert result is not None
    by_name = {m['material_name']: m for m in result['materials']}
    assert by_name['面料A']['part_name'] == '身体'
    assert by_name['拉链']['part_name'] == '头部'
    assert by_name['棉花/填充物']['part_name'] is None


# ===== 复制 =====

async def test_copy_bom_copies_part_name_on_default_scope(db_session):
    db = db_session
    await _seed_source_with_parts(db)

    await bom_service.copy_bom(
        db, 2, {'source_product_id': 1, 'overwrite': False}, 'tester',
    )
    await db.flush()

    fabric = (await db.execute(
        select(ProductFabric).where(ProductFabric.product_id == 2)
    )).scalar_one()
    accessory = (await db.execute(
        select(ProductAccessory).where(ProductAccessory.product_id == 2)
    )).scalar_one()
    material = (await db.execute(
        select(ProductMaterial).where(ProductMaterial.product_id == 2)
    )).scalar_one()

    assert fabric.part_name == '身体'
    assert accessory.part_name == '头部'
    assert material.part_name == '躯干'


async def test_copy_bom_into_role_copies_part_name(db_session):
    db = db_session
    await _seed_source_with_parts(db)
    db.add(ProductRole(product_id=2, role_name='目标角色'))
    await db.commit()

    await bom_service.copy_bom(
        db, 2,
        {'source_product_id': 1, 'overwrite': False, 'role_name': '目标角色'},
        'tester',
    )
    await db.flush()

    role = (await db.execute(
        select(ProductRole).where(
            ProductRole.product_id == 2,
            ProductRole.role_name == '目标角色',
        )
    )).scalar_one()
    fabric = (await db.execute(
        select(ProductFabric).where(
            ProductFabric.product_id == 2, ProductFabric.role_id == role.id,
        )
    )).scalar_one()
    accessory = (await db.execute(
        select(ProductAccessory).where(
            ProductAccessory.product_id == 2, ProductAccessory.role_id == role.id,
        )
    )).scalar_one()
    material = (await db.execute(
        select(ProductMaterial).where(
            ProductMaterial.product_id == 2, ProductMaterial.role_id == role.id,
        )
    )).scalar_one()

    assert fabric.part_name == '身体'
    assert accessory.part_name == '头部'
    assert material.part_name == '躯干'


async def test_bom_preview_includes_part_name(db_session):
    db = db_session
    await _seed_source_with_parts(db)

    preview = await purchase_bom_copy_service.get_bom_preview(db, 1)
    assert preview['bom']['filling']['part_name'] == '躯干'
    assert preview['bom']['fabric'][0]['part_name'] == '身体'
    assert preview['bom']['accessory'][0]['part_name'] == '头部'
