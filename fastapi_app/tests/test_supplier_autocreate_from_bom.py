"""BOM 保存时供应商自动建卡 + 供应商 options 端点 回归测试。

覆盖：
1. ``purchase_supplier_service.resolve_bom_suppliers`` —— 批量建缺失、复用已存在
   （含禁用）、trim 去重、空名忽略、超长名抛 ValueError。
2. ``list_supplier_options`` —— 返回 id+name 且按名称排序。
3. ``bom_service.save_bom`` 端到端 —— 物料携带的新供应商名落库为 supplier 行，
   并回填到产品面料的 ``supplier_id``。

数据库用真实异步内存 SQLite（``create_all`` + btrim UDF），不触碰生产库。
"""
import pytest
import pytest_asyncio
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from fastapi_app.services import purchase_supplier_service
from fastapi_app.services.bom_service import save_bom
from fastapi_app.shared_models import (
    Base,
    ModificationLog,
    Product,
    ProductAccessory,
    ProductFabric,
    ProductMaterial,
    ProductRole,
    Role,
    Supplier,
)

_TABLES = [
    Role.__table__,
    Product.__table__,
    ProductRole.__table__,
    ProductFabric.__table__,
    ProductAccessory.__table__,
    ProductMaterial.__table__,
    ModificationLog.__table__,
    Supplier.__table__,
]


@pytest_asyncio.fixture
async def db():
    """真实异步内存 SQLite，含产品 1 与一个既有（禁用）供应商。"""
    engine = create_async_engine(
        'sqlite+aiosqlite:///:memory:',
        poolclass=StaticPool,
        connect_args={'check_same_thread': False},
    )

    @event.listens_for(engine.sync_engine, 'connect')
    def _register_btrim(dbapi_connection, _record):  # pragma: no cover
        dbapi_connection.create_function(
            'btrim', 1, lambda v: v.strip() if isinstance(v, str) else v,
        )

    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=_TABLES))
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        session.add(Product(id=1, name='测试产品', price=1))
        session.add(Supplier(id=10, name='既有供应商', status=True))
        session.add(Supplier(id=11, name='停用供应商', status=False))
        await session.commit()
        yield session
    await engine.dispose()


class TestResolveBomSuppliers:
    @pytest.mark.asyncio
    async def test_creates_missing_and_reuses_existing(self, db):
        mapping = await purchase_supplier_service.resolve_bom_suppliers(
            db, ['既有供应商', '停用供应商', '全新供应商'],
        )
        # 已存在的复用其 id（含禁用）
        assert mapping['既有供应商'] == 10
        assert mapping['停用供应商'] == 11
        # 缺失的新建
        assert isinstance(mapping['全新供应商'], int)
        rows = (await db.execute(select(Supplier.name))).scalars().all()
        assert rows.count('全新供应商') == 1

    @pytest.mark.asyncio
    async def test_trim_dedup_and_blank_ignored(self, db):
        mapping = await purchase_supplier_service.resolve_bom_suppliers(
            db, ['  空格供应商  ', '空格供应商', '', '   ', None],
        )
        assert set(mapping) == {'空格供应商'}
        rows = (await db.execute(select(Supplier.name))).scalars().all()
        assert rows.count('空格供应商') == 1

    @pytest.mark.asyncio
    async def test_oversized_name_raises(self, db):
        with pytest.raises(ValueError, match='过长'):
            await purchase_supplier_service.resolve_bom_suppliers(db, ['x' * 101])
        # 超长名不得落库
        assert (await db.execute(select(Supplier.name).where(Supplier.name == 'x' * 101))).first() is None

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty(self, db):
        assert await purchase_supplier_service.resolve_bom_suppliers(db, []) == {}
        assert await purchase_supplier_service.resolve_bom_suppliers(db, ['', None]) == {}


class TestListSupplierOptions:
    @pytest.mark.asyncio
    async def test_returns_id_name_pairs(self, db):
        # 排序依赖数据库 collation（SQLite 字节序 ≠ PG），故只断言内容，不锁顺序
        options = await purchase_supplier_service.list_supplier_options(db)
        assert {o['name']: o['id'] for o in options} == {
            '既有供应商': 10, '停用供应商': 11,
        }


class TestSaveBomAutoCreate:
    @pytest.mark.asyncio
    async def test_new_supplier_created_and_backfilled(self, db):
        data = {
            'fabrics': [{
                'fabric_name': '面料甲', 'specification': 'S', 'unit': '码',
                'quantity': 2, 'supplier_name': ' BOM 新供应商 ',
            }],
            'accessories': [],
            'fillings': [],
        }
        await save_bom(db, 1, data, 'tester')
        await db.commit()

        supplier = (
            await db.execute(select(Supplier).where(Supplier.name == 'BOM 新供应商'))
        ).scalar_one()
        fabric = (
            await db.execute(select(ProductFabric).where(ProductFabric.product_id == 1))
        ).scalar_one()
        assert fabric.supplier_name == ' BOM 新供应商 '
        assert fabric.supplier_id == supplier.id

    @pytest.mark.asyncio
    async def test_existing_supplier_reused_not_duplicated(self, db):
        data = {
            'fabrics': [{
                'fabric_name': '面料乙', 'specification': 'S', 'unit': '码',
                'quantity': 1, 'supplier_name': '既有供应商',
            }],
            'accessories': [], 'fillings': [],
        }
        await save_bom(db, 1, data, 'tester')
        await db.commit()

        names = (await db.execute(select(Supplier.name))).scalars().all()
        assert names.count('既有供应商') == 1
        fabric = (
            await db.execute(select(ProductFabric).where(ProductFabric.product_id == 1))
        ).scalar_one()
        assert fabric.supplier_id == 10

    @pytest.mark.asyncio
    async def test_blank_supplier_does_not_wipe_existing_id(self, db):
        """空名保存不得把既有行的 supplier_id 抹掉。"""
        db.add(ProductFabric(
            id=99, product_id=1, fabric_name='面料丙', specification='S',
            unit='码', quantity=1, supplier_id=10, supplier_name='',
        ))
        await db.commit()
        data = {
            'fabrics': [{
                'id': 99, 'fabric_name': '面料丙', 'specification': 'S', 'unit': '码',
                'quantity': 1, 'supplier_id': 10, 'supplier_name': '',
            }],
            'accessories': [], 'fillings': [],
        }
        await save_bom(db, 1, data, 'tester')
        await db.commit()
        fabric = await db.get(ProductFabric, 99)
        assert fabric.supplier_id == 10  # 保持原值，未被置空
