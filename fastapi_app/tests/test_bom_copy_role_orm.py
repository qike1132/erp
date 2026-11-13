"""
BOM 复制·真实 ORM 语义回归测试

覆盖对象：``copy_bom`` 的 **role_name 分支**（复制到前端未保存的新角色）在
**真实 SQLAlchemy session** 下的行为。

为什么必须用真实 session
------------------------
``test_bom_role.py`` 中的 ``_mock_product`` 是 ``MagicMock`` + 普通 ``list``，
它无法复现 ``Product.roles``（``product.py:74``）的 ``lazy="raise"`` 与
``InstrumentedList`` 语义，因此以下两类回归在 mock 用例下会**静默通过**：

1. ``copy_bom`` 查询目标产品时漏掉 ``selectinload(Product.roles)``
   → 新建角色分支访问 ``target_product.roles`` 抛
     ``InvalidRequestError: 'Product.roles' is not available due to lazy='raise'``；
2. 新建角色后漏掉 ``target_product.roles.append(role)``
   → ``_copy_bom_into_role`` 的归属校验取不到该角色，抛
     ``ValueError('目标角色不存在或不属于该产品')``。

本用例在内存 SQLite 上跑通真实关系加载与归属校验，可证伪上述两类回归。
仅使用内存库，不触碰生产数据。
"""
from decimal import Decimal

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from fastapi_app.services import bom_service
from fastapi_app.shared_models import Base, Role
from fastapi_app.shared_models.product import Product
from fastapi_app.shared_models.product_material import (
    ProductAccessory,
    ProductFabric,
    ProductMaterial,
    ProductRole,
)

# 仅建 copy_bom 路径上会被访问的表，避免拖入无关依赖链。
# Role 表保留：ProductRole.global_role_id 的 FK 仍指向 role.id（迁移 089 才删）。
_TABLES = [
    Role.__table__,
    Product.__table__,
    ProductRole.__table__,
    ProductFabric.__table__,
    ProductAccessory.__table__,
    ProductMaterial.__table__,
]


@pytest_asyncio.fixture
async def real_db_session():
    """真实异步 SQLAlchemy session（内存 SQLite，StaticPool 保证同一连接同一库）。"""
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


async def _seed(db) -> None:
    """源产品含默认作用域（role_id 为 NULL）的填充/面料/辅料；目标产品含一个已有角色。

    角色为产品私有（迁移 088/089）：ProductRole 只按 ``role_name`` 建行，不再需要全局角色。
    """
    db.add_all([
        Product(id=1, name='ORM回归-源产品', price=1),
        Product(id=2, name='ORM回归-目标产品', price=1),
    ])
    await db.flush()
    db.add_all([
        ProductMaterial(product_id=1, role_id=None, cotton_usage=Decimal('120'), unit='克'),
        ProductFabric(product_id=1, role_id=None, fabric_name='超柔', quantity=Decimal('0.5'), unit='码'),
        ProductAccessory(product_id=1, role_id=None, accessory_name='拉链', quantity=Decimal('1'), unit='个'),
        ProductRole(product_id=2, role_name='目标已有角色'),
    ])
    await db.commit()


async def test_copy_bom_creates_new_role_by_name_on_real_session(real_db_session):
    """真实 ORM 下按 role_name 新建角色并复制物料：不得抛错，物料归属新角色。"""
    db = real_db_session
    await _seed(db)

    # 不抛异常即为通过（漏 selectinload / 漏 append 都会在此抛错）
    result = await bom_service.copy_bom(
        db, 2, {'source_product_id': 1, 'overwrite': False, 'role_name': '新角色X'}, 'tester',
    )
    assert isinstance(result, dict)

    # a) 新建了名为「新角色X」的 ProductRole
    role = (await db.execute(
        select(ProductRole).where(
            ProductRole.product_id == 2,
            ProductRole.role_name == '新角色X',
        )
    )).scalar_one_or_none()
    assert role is not None, '未新建 ProductRole（role_name 分支未生效）'
    assert role.role_name == '新角色X'

    # b) 复制出的面料/辅料/填充的 role_id 全部等于新角色 id
    fabrics = (await db.execute(
        select(ProductFabric).where(ProductFabric.product_id == 2)
    )).scalars().all()
    accessories = (await db.execute(
        select(ProductAccessory).where(ProductAccessory.product_id == 2)
    )).scalars().all()
    materials = (await db.execute(
        select(ProductMaterial).where(ProductMaterial.product_id == 2)
    )).scalars().all()

    assert len(fabrics) == 1 and {f.role_id for f in fabrics} == {role.id}
    assert len(accessories) == 1 and {a.role_id for a in accessories} == {role.id}
    assert len(materials) == 1 and {m.role_id for m in materials} == {role.id}
    assert result['copied_count'] == 3
    assert result['target_role'] == {'id': role.id, 'name': '新角色X'}

    # 目标产品原有角色未被波及（未重建、未删除）
    roles = (await db.execute(
        select(ProductRole).where(ProductRole.product_id == 2)
    )).scalars().all()
    assert {r.role_name for r in roles} == {'目标已有角色', '新角色X'}


async def test_full_copy_from_role_only_source_copies_whole_structure(real_db_session):
    """源产品的物料全挂在角色下时，整份复制必须把角色和物料一起搬到目标产品。

    生产缺陷（2026-11-13）：源 SKU 6 个角色共 27 条物料、默认作用域为空；
    前端把当前选中角色透传为 role_id 后，后端只搬默认作用域 → 复制 0 条仍返回
    成功，页面显示「复制成功」后仍是「暂无物料」。修复后快速复制不再传 role_id，
    走本用例覆盖的整份复制路径。
    """
    db = real_db_session
    db.add_all([
        Product(id=3, name='角色化源产品', price=1),
        Product(id=4, name='目标产品', price=1),
    ])
    await db.flush()
    source_role = ProductRole(product_id=3, role_name='香蕉')
    target_role = ProductRole(product_id=4, role_name='默认')
    db.add_all([source_role, target_role])
    await db.flush()
    db.add_all([
        ProductFabric(
            product_id=3, role_id=source_role.id, fabric_name='超柔',
            specification='338#', quantity=Decimal('0.5'), unit='码',
        ),
        ProductAccessory(
            product_id=3, role_id=source_role.id, accessory_name='拉链',
            specification='白', quantity=Decimal('1'), unit='个',
        ),
    ])
    await db.commit()

    result = await bom_service.copy_bom(
        db, 4, {'source_product_id': 3, 'overwrite': True}, 'tester',
    )
    await db.commit()

    roles = (await db.execute(
        select(ProductRole).where(ProductRole.product_id == 4)
    )).scalars().all()
    fabrics = (await db.execute(
        select(ProductFabric).where(ProductFabric.product_id == 4)
    )).scalars().all()
    accessories = (await db.execute(
        select(ProductAccessory).where(ProductAccessory.product_id == 4)
    )).scalars().all()

    assert {r.role_name for r in roles} == {'香蕉'}, '整份复制应重建源产品角色结构'
    assert len(fabrics) == 1 and fabrics[0].fabric_name == '超柔'
    assert len(accessories) == 1 and accessories[0].accessory_name == '拉链'
    assert fabrics[0].role_id == roles[0].id
    assert result['copied_count'] >= 3  # 角色 + 面料 + 辅料
