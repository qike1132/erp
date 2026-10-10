"""BOM 复制·默认分支「复制源产品角色」的真实 ORM 守卫测试（角色**产品私有**）。

覆盖缺口
--------
``bom_service.copy_bom`` 在 ``role_id`` 与 ``role_name`` 均未传时走「原有逻辑」分支，
其中包含「复制源产品角色及其独立物料」的循环。该循环此前无真实会话覆盖：

- ``test_bom_copy_role_orm.py`` 只给**目标产品**建了 ``ProductRole``，**源产品**
  ``roles`` 为空 ⇒ 循环体从不执行；
- ``test_bom_role.py::TestCopyBom`` 用 ``MagicMock``/``AsyncMock`` 假会话。

本用例用**真实内存 SQLite + ``Base.metadata.create_all``** 驱动默认分支：源产品挂一个
角色 + 角色级面料/辅料，断言复制后目标产品新增**同名** ``ProductRole``、复制出的物料
``role_id`` 指向该新行。角色为**产品私有**（迁移 088/089）：复制按**角色名**去重，
不再复用全局角色 id。

仅使用内存库，不触碰生产数据。
"""
from decimal import Decimal

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from fastapi_app.services import bom_service
from fastapi_app.shared_models import Base
from fastapi_app.shared_models.product import Product
from fastapi_app.shared_models.product_material import (
    ProductAccessory,
    ProductFabric,
    ProductMaterial,
    ProductRole,
)

# 仅建 copy_bom 默认分支会访问到的表。
_TABLES = [
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


async def _seed_source_role(db) -> ProductRole:
    """源产品（id=1）挂一个角色 + 角色级面料/辅料；目标产品（id=2）留空。"""
    db.add_all([
        Product(id=1, name='复制守卫-源产品', price=1),
        Product(id=2, name='复制守卫-目标产品', price=1),
    ])
    await db.flush()

    src_assoc = ProductRole(product_id=1, role_name='源角色A')
    db.add(src_assoc)
    await db.flush()

    db.add_all([
        ProductFabric(
            product_id=1, role_id=src_assoc.id, fabric_name='源角色A面料',
            quantity=Decimal('2'), unit='码',
        ),
        ProductAccessory(
            product_id=1, role_id=src_assoc.id, accessory_name='源角色A辅料',
            quantity=Decimal('1'), unit='个',
        ),
    ])
    await db.commit()
    return src_assoc


async def _rows_for(db, model, product_id: int) -> list:
    result = await db.execute(select(model).where(model.product_id == product_id))
    return list(result.scalars().all())


async def test_copy_bom_default_branch_creates_named_target_role(real_db_session):
    """默认分支复制源产品角色：目标新增**同名**关联行，复制物料挂到该新行。"""
    db = real_db_session
    src_assoc = await _seed_source_role(db)

    result = await bom_service.copy_bom(
        db, 2, {'source_product_id': 1, 'overwrite': False}, 'tester',
    )
    await db.flush()

    # a) 目标产品新增 1 条 ProductRole，名字与源角色一致（产品私有：按名复制）
    target_roles = await _rows_for(db, ProductRole, 2)
    assert len(target_roles) == 1, f'应复制出 1 条目标角色，实得 {len(target_roles)}'
    new_role = target_roles[0]
    assert new_role.role_name == '源角色A'
    assert new_role.id != src_assoc.id, '目标关联行必须是新行，不得复用源关联行 id'

    # b) 复制出的角色级面料/辅料 role_id 指向新关联行
    tgt_fabrics = await _rows_for(db, ProductFabric, 2)
    tgt_accessories = await _rows_for(db, ProductAccessory, 2)
    assert len(tgt_fabrics) == 1 and {f.role_id for f in tgt_fabrics} == {new_role.id}
    assert len(tgt_accessories) == 1 and {a.role_id for a in tgt_accessories} == {new_role.id}

    # c) 计数 = 1 角色 + 1 面料 + 1 辅料（源产品无产品级默认物料）
    assert result['copied_count'] == 3


async def test_copy_bom_default_branch_reuses_existing_named_target_role(real_db_session):
    """目标已有**同名**角色 → 复用该关联行（不新建），物料挂到既有行。"""
    db = real_db_session
    db.add_all([
        Product(id=1, name='复制去重-源产品', price=1),
        Product(id=2, name='复制去重-目标产品', price=1),
    ])
    await db.flush()

    src_assoc = ProductRole(product_id=1, role_name='源角色A')
    tgt_assoc = ProductRole(product_id=2, role_name='源角色A')
    db.add_all([src_assoc, tgt_assoc])
    await db.flush()
    db.add(ProductFabric(
        product_id=1, role_id=src_assoc.id, fabric_name='源角色A面料',
        quantity=Decimal('2'), unit='码',
    ))
    await db.commit()

    await bom_service.copy_bom(db, 2, {'source_product_id': 1, 'overwrite': False}, 'tester')
    await db.flush()

    target_roles = await _rows_for(db, ProductRole, 2)
    assert len(target_roles) == 1, '目标已有同名角色 → 必须复用，不得新建'
    assert target_roles[0].id == tgt_assoc.id

    tgt_fabrics = await _rows_for(db, ProductFabric, 2)
    assert len(tgt_fabrics) == 1 and tgt_fabrics[0].role_id == tgt_assoc.id
