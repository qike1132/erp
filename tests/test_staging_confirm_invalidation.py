"""暂存确认（staging confirm）必须失效库存缓存 —— 2026-10-13 评审发现的漏点。

背景：`/stock` 的「库存/备货/订单」三列读 `inventory:paginated`（ttl=120s）。
`confirm_staging_stockins` / `confirm_staging_stockouts` / `confirm_staging_orders`
会写**真实的** `stock_in` / `stock_out` / `order` + `inventory_log` +
`product.current_stock` —— 全是该缓存键的输入表，但三条路径此前**一处失效都没有**：

    grep -rn "invalidate" fastapi_app/services/staging/   →  无命中

后果：前端「出货导入」确认后，`/stock` 最长 120s 继续显示旧数（而 TTL 一旦调长，
这个陈旧窗口会跟着放大）。入库/出库/退货/生产四条同类写路径都有这道失效
（见 `tests/test_post_commit_invalidation.py`），此处补齐并锁死。

断言的是「登记了 post-commit 失效回调」这一接线事实 —— 与既有同类测试同款。
"""
import itertools
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fastapi_app.core.cache_invalidation import cache_mgr
from fastapi_app.core.state_machine import StagingStatus
from fastapi_app.services import staging_service
from fastapi_app.shared_models import (
    DailyProductionRecord,
    Order,
    Product,
    StagingOrder,
    StagingStockIn,
    StagingStockOut,
)

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def db(test_engine):
    """事务回滚隔离的会话（与 tests/test_post_commit_invalidation.py 同款）。"""
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False,
    )
    async with factory() as session:
        async with session.begin() as transaction:
            yield session
            await transaction.rollback()


@pytest.fixture(autouse=True)
def _stub_numbering(monkeypatch):
    """打桩单号分配：它依赖全局引擎（`init_async_engine`），夹具会话提供不了。

    本测试的被测行为是「确认后有没有登记缓存失效」，单号分配是无关的外部依赖，
    按仓库规矩用打桩隔离；序号自增，避免与真实单号撞唯一约束。
    """
    from fastapi_app.services.staging import order as order_mod
    from fastapi_app.services.staging import stockin as stockin_mod
    from fastapi_app.services.staging import stockout as stockout_mod

    seq = itertools.count(1)

    async def _next_no(prefix: str, db) -> str:
        return f'{prefix}-PCI{next(seq):04d}'

    monkeypatch.setattr(stockin_mod, 'generate_stockin_number', lambda db: _next_no('BH', db))
    monkeypatch.setattr(stockout_mod, 'generate_stockout_number', lambda db: _next_no('SO', db))
    monkeypatch.setattr(order_mod, 'generate_order_number', lambda db: _next_no('PO', db))


def _registered_callbacks(db: AsyncSession) -> list:
    return db.info.get('post_commit_callbacks', [])


async def _seed_product(db: AsyncSession, barcode: str, stock: int = 0) -> Product:
    product = Product(name=f'PCI-{barcode}', barcode=barcode, current_stock=stock, initial_stock=stock)
    db.add(product)
    await db.flush()
    return product


async def _seed_packaging(db: AsyncSession, product: Product, quantity: int) -> None:
    """补一条包装部入库。

    2026-10-24：出货闸门读「可出库存 = 包装部入库 − 已出货」，备货/填充/手工都不计入
    （业务口径）。夹具原先只给 current_stock，结余恒 0 → 确认被拒。真实业务里
    这笔成品必然有包装部入库记录，故按真实链路补上。
    """
    db.add(DailyProductionRecord(
        department='packaging', product_id=product.id, product_name=product.name,
        barcode=product.barcode or '', quantity=quantity, production_date=date.today(),
    ))
    await db.flush()


async def test_confirm_staging_stockins_registers_post_commit_invalidation(db):
    """备货确认会写 stock_in + inventory_log + product.current_stock，必须失效库存缓存。"""
    product = await _seed_product(db, 'PCI-STG-IN')
    db.add(StagingStockIn(
        session_id='pci-in', customer='PCI客户', product_name=product.name,
        product_id=product.id, quantity=5,
        status=StagingStatus.PENDING, is_validated=True,
    ))
    await db.flush()

    confirmed, errors = await staging_service.confirm_staging_stockins(db, 'pci-in')

    assert confirmed == 1, f'夹具应确认成功，实际 errors={errors}'
    assert cache_mgr.invalidate_stock_and_order in _registered_callbacks(db)


async def test_confirm_staging_stockouts_registers_post_commit_invalidation(db):
    """出货确认会写 stock_out + inventory_log + product.current_stock，必须失效库存缓存。"""
    product = await _seed_product(db, 'PCI-STG-OUT', stock=100)
    await _seed_packaging(db, product, 100)
    # 出货确认要求「有可用订单支持」，先造一张足量订单
    db.add(Order(
        order_no='PCI-STG-OUT-ORD', customer='PCI客户',
        product_id=product.id, quantity=50, status='待备货',
    ))
    db.add(StagingStockOut(
        session_id='pci-out', customer='PCI客户', product_name=product.name,
        product_id=product.id, quantity=5,
        status=StagingStatus.PENDING, is_validated=True, stock_check_passed=True,
    ))
    await db.flush()

    confirmed, errors = await staging_service.confirm_staging_stockouts(db, 'pci-out')

    assert confirmed == 1, f'夹具应确认成功，实际 errors={errors}'
    assert cache_mgr.invalidate_stock_and_order in _registered_callbacks(db)


async def test_confirm_staging_orders_registers_post_commit_invalidation(db):
    """订单确认会写 order + inventory_log + product.current_stock，必须失效库存缓存。"""
    product = await _seed_product(db, 'PCI-STG-ORD')
    db.add(StagingOrder(
        session_id='pci-ord', customer='PCI客户', product_name=product.name,
        product_id=product.id, quantity=7,
        status=StagingStatus.PENDING, is_validated=True,
    ))
    await db.flush()

    confirmed, errors = await staging_service.confirm_staging_orders(db, 'pci-ord')

    assert confirmed == 1, f'夹具应确认成功，实际 errors={errors}'
    assert cache_mgr.invalidate_stock_and_order in _registered_callbacks(db)
