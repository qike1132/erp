"""BOM 角色「产品私有」核心行为验收（迁移 088/089）。

覆盖本次改造的语义核心：
1. **产品内**角色名大小写不敏感唯一 → 冲突抛 ``BusinessError``（→ HTTP 400）；
2. **跨产品**同名互不影响（角色私有，改一个不动另一个）；
3. ``get_bom`` 角色输出收敛为 ``{id, name}``（不再有 ``global_role_id``）。

自带真实内存 SQLite engine（``create_all``），不依赖 conftest、不触碰生产数据。
"""
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from fastapi_app.core.exceptions import BusinessError
from fastapi_app.services import bom_service
from fastapi_app.shared_models import Base, ModificationLog, Supplier
from fastapi_app.shared_models.product import Product
from fastapi_app.shared_models.product_material import (
    ProductAccessory,
    ProductFabric,
    ProductMaterial,
    ProductRole,
)

_TABLES = [
    Product.__table__,
    ProductRole.__table__,
    ProductFabric.__table__,
    ProductAccessory.__table__,
    ProductMaterial.__table__,
    ModificationLog.__table__,
    Supplier.__table__,
]

_ROLE_SAVE = {'roles': [], 'fabrics': [], 'accessories': [], 'fillings': []}


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(
        'sqlite+aiosqlite:///:memory:',
        poolclass=StaticPool,
        connect_args={'check_same_thread': False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=_TABLES))
    # autoflush=False：与生产会话配置一致（fastapi_app/core/database.py）。
    # 关键：save_bom 会先插入物料、再删「未提交」物料；若 autoflush=True，新插入的行
    # 会被随后的删除查询看到并误删（生产靠 autoflush=False 规避）。
    async with async_sessionmaker(engine, expire_on_commit=False, autoflush=False)() as session:
        session.add_all([Product(id=1, name='P1', price=1), Product(id=2, name='P2', price=1)])
        await session.commit()
        yield session
    await engine.dispose()


def _save(payload: dict) -> dict:
    return {**_ROLE_SAVE, **payload}


async def _role_of(db, product_id: int, *, by_name: str | None = None) -> ProductRole:
    stmt = select(ProductRole).where(ProductRole.product_id == product_id)
    if by_name is not None:
        stmt = stmt.where(ProductRole.role_name == by_name)
    return (await db.execute(stmt)).scalars().first()


class TestPerProductNameUniqueness:
    async def test_duplicate_name_in_payload_rejected(self, db):
        """同一 payload 内两个名字仅大小写不同 → 产品内重名，拒绝。"""
        with pytest.raises(BusinessError, match='重复'):
            await bom_service.save_bom(
                db, 1, _save({'roles': [{'role_name': '角色A'}, {'role_name': '角色a'}]}), 'tester',
            )

    async def test_rename_to_existing_name_rejected(self, db):
        """把角色 B 改名成已存在的 A → 拒绝。"""
        await bom_service.save_bom(
            db, 1, _save({'roles': [{'role_name': '角色A'}, {'role_name': '角色B'}]}), 'tester',
        )
        rows = (await db.execute(
            select(ProductRole).where(ProductRole.product_id == 1).order_by(ProductRole.id)
        )).scalars().all()
        assert [r.role_name for r in rows] == ['角色A', '角色B']
        with pytest.raises(BusinessError, match='重复'):
            await bom_service.save_bom(db, 1, _save({'roles': [
                {'id': rows[0].id, 'role_name': '角色A'},
                {'id': rows[1].id, 'role_name': '角色A'},
            ]}), 'tester')


class TestCrossProductIsolation:
    async def test_same_name_across_products_are_independent(self, db):
        """两个 SKU 建同名角色 → 各自独立行；改一个，另一个不变。"""
        await bom_service.save_bom(db, 1, _save({'roles': [{'role_name': '共用角色'}]}), 'tester')
        await bom_service.save_bom(db, 2, _save({'roles': [{'role_name': '共用角色'}]}), 'tester')

        r1 = await _role_of(db, 1)
        r2 = await _role_of(db, 2)
        assert r1 is not None and r2 is not None
        assert r1.id != r2.id, '同名角色在不同产品下必须是不同的行'

        # 改产品 1 的名字 + 一条 BOM 物料归属，产品 2 必须毫发无损
        await bom_service.save_bom(db, 1, _save({
            'roles': [{'id': r1.id, 'role_name': '改名后'}],
            'fabrics': [{'fabric_name': '布', 'specification': 's', 'unit': '码',
                         'quantity': 1, 'supplier_name': '', 'role_id': r1.id}],
        }), 'tester')

        await db.refresh(r2)
        assert r2.role_name == '共用角色', '改动产品 1 的角色名不得影响产品 2'
        assert (await db.get(ProductRole, r1.id)).role_name == '改名后'
        assert (await _role_of(db, 2)).role_name == '共用角色'


class TestGetBomRoleShape:
    async def test_roles_output_is_id_and_name_only(self, db):
        await bom_service.save_bom(db, 1, _save({'roles': [{'role_name': '甲'}]}), 'tester')
        result = await bom_service.get_bom(db, 1)
        assert result is not None
        assert len(result['roles']) == 1
        assert set(result['roles'][0].keys()) == {'id', 'name'}
        assert result['roles'][0]['name'] == '甲'

    async def test_role_materials_keep_role_id_link(self, db):
        """角色私有化不动物料归属：物料 role_id 指向本产品角色行 id。"""
        await bom_service.save_bom(db, 1, _save({'roles': [{'role_name': '甲'}]}), 'tester')
        role = await _role_of(db, 1)

        await bom_service.save_bom(db, 1, _save({
            'roles': [{'id': role.id, 'role_name': '甲'}],
            'fabrics': [{'fabric_name': '布', 'specification': 's', 'unit': '码',
                         'quantity': Decimal('2'), 'supplier_name': '', 'role_id': role.id}],
        }), 'tester')
        await db.commit()  # 真实端点由 db_transaction 提交；autoflush=False 故需显式提交才可见

        fabric = (await db.execute(
            select(ProductFabric).where(ProductFabric.product_id == 1)
        )).scalar_one()
        assert fabric.role_id == role.id
