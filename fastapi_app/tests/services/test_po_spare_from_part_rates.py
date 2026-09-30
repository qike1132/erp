"""备品按部位损耗率重算（公式 A：瓶颈部位决定）回归测试。

口径见 docs/purchase/备品数量按部位差异化损耗率计算方案.md。
核心不变量：备品 = Σ_SKU ceil(SKU订单数量 × max(该SKU各部位行损耗率)‰)。
降级不变量：任何数据不可得时回退既有订单级口径，绝不抛错、绝不清零。
"""
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from fastapi_app.services.purchase_order_spare import _load_bom_item_keys
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
)

_XIAOTU = '兔子公仔'

# 全部用例共用的建表清单：Task 4 的完成路径会写 MaterialRegistration /
# MaterialRegistrationItem / ModificationLog，故一并建出（对 Task 1-3 无害）。
_TABLES = [
    Product.__table__, ProductFabric.__table__, ProductMaterial.__table__,
    ProductAccessory.__table__, PurchaseOrder.__table__,
    PurchaseOrderItem.__table__, PurchaseOrderSku.__table__,
    MaterialRegistration.__table__, MaterialRegistrationItem.__table__,
    ModificationLog.__table__,
]


@pytest_asyncio.fixture
async def db():
    """真实模型的 sqlite 内存库会话。

    不建 Role / Supplier 等表亦可 —— sqlite 不校验 FK 目标是否存在，
    且本模块的 BOM 键加载不依赖角色名（按 role_id 全量读取，不区分作用域）。
    """
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=_TABLES))
    maker = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _seed_product_with_bom(db: AsyncSession, pid: int = 9001) -> int:
    """一个产品 + 三类 BOM 各一行（口径见 _MATERIAL_SPECS）。"""
    db.add(Product(id=pid, name=_XIAOTU))
    db.add(ProductMaterial(
        id=pid * 10 + 1, product_id=pid, cotton_usage=10, specification='填充A', unit='克',
    ))
    db.add(ProductFabric(
        id=pid * 10 + 2, product_id=pid, fabric_name='对条头布',
        specification='S1', quantity=0.2, unit='米',
    ))
    db.add(ProductAccessory(
        id=pid * 10 + 3, product_id=pid, accessory_name='眼睛扣',
        specification='', quantity=2, unit='个',
    ))
    await db.commit()
    return pid


async def test_load_bom_item_keys_matches_generation_naming(db):
    """BOM 键必须与采购明细生成口径逐字一致（三类物料各一行）。"""
    session = db
    pid = await _seed_product_with_bom(session)

    keys = await _load_bom_item_keys(session, {pid: _XIAOTU})

    assert keys[pid] == {
        (f'{_XIAOTU}-填充物', '填充A', '克'),
        ('对条头布', 'S1', '米'),
        ('眼睛扣', '', '个'),
    }


async def test_load_bom_item_keys_empty_products_returns_empty(db):
    """无产品 → 空映射（不得发起查询、不得抛错）。"""
    assert await _load_bom_item_keys(db, {}) == {}


async def test_load_bom_item_keys_missing_tables_degrades(db):
    """BOM 表不可用 → 返回空映射并降级，绝不抛错。"""
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    maker = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as bare:
        assert await _load_bom_item_keys(bare, {1: '不存在'}) == {}
    await engine.dispose()
