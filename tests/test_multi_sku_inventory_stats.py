"""多 SKU 库存统计集成测试（A 类统计改造，2026-08-22）

验证 OrderItem 维度聚合的正确性：
- 混合 SKU 订单（regular + custom 各一条明细）按明细分类统计
- 无明细兼容订单（批量导入路径）回退订单级字段（COALESCE）
- 库存聚合按 SKU 维度拆分，国家归属取明细 country
- 出库列表 order_type/country 按匹配明细判定

自包含 fixture（函数级引擎/会话）：不依赖 root conftest 的 session 级
test_engine（与本机 pytest-asyncio 1.x 存在 ScopeMismatch），只写测试库
erp_system_test，事务回滚隔离。
"""
import os
from datetime import UTC, datetime
from urllib.parse import urlparse, urlunparse

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from fastapi_app.services.stock_inventory_service import (
    _fetch_inventory,
    get_stock_overview_stats,
    get_stockouts,
)
from fastapi_app.shared_models import Base, Order, OrderItem, Product, StockOut

pytestmark = pytest.mark.integration

CUSTOMER = '多SKU测试客户'


def _test_db_url() -> str:
    override = os.getenv('TEST_DATABASE_URL')
    if override:
        return override
    from fastapi_app.core.config import settings
    db_name = os.getenv('DB_NAME', 'erp_system')
    parsed = urlparse(settings.ASYNC_DATABASE_URL)
    new_path = parsed.path.replace(f'/{db_name}', f'/{db_name}_test', 1)
    return urlunparse(parsed._replace(path=new_path))


@pytest_asyncio.fixture
async def db():
    """函数级测试会话：建表 + 事务回滚隔离（自包含，不依赖 session 级 fixture）"""
    engine = create_async_engine(_test_db_url(), echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        async with session.begin() as transaction:
            yield session
            await transaction.rollback()
    await engine.dispose()


@pytest.fixture
async def products_ab(db):
    products = [
        Product(name='多SKU产品A', barcode='MSKU-A', current_stock=0, initial_stock=0),
        Product(name='多SKU产品B', barcode='MSKU-B', current_stock=0, initial_stock=0),
    ]
    for p in products:
        db.add(p)
    await db.flush()
    return products


@pytest.fixture
async def mixed_order(db, products_ab):
    """混合 SKU 订单：A 产品 regular 3 件 + B 产品 custom 2 件（国家=法国）。

    订单级兼容字段故意写成首 item 值（regular / product_id=A / quantity=5），
    旧实现在此数据下统计错误，新实现应按明细得出 3/2。
    """
    order = Order(
        order_no='MSKU-MIX-001', customer=CUSTOMER, order_date=datetime.now(UTC),
        product_id=products_ab[0].id, quantity=5, order_type='regular', status='待备货',
    )
    db.add(order)
    await db.flush()
    db.add(OrderItem(
        order_id=order.id, product_id=products_ab[0].id, quantity=3, order_type='regular'))
    db.add(OrderItem(
        order_id=order.id, product_id=products_ab[1].id, quantity=2, order_type='custom', country='法国'))
    await db.flush()
    return order


@pytest.fixture
async def legacy_order(db, products_ab):
    """无明细兼容订单（模拟批量导入路径）：A 产品 regular 5 件。"""
    order = Order(
        order_no='MSKU-LEG-001', customer=CUSTOMER, order_date=datetime.now(UTC),
        product_id=products_ab[0].id, quantity=5, order_type='regular', status='待备货',
    )
    db.add(order)
    await db.flush()
    return order


async def test_overview_stats_item_dimension(db, products_ab, mixed_order):
    """混合 SKU 订单：常规/定制数量按明细分类（旧实现会得出 5/0）"""
    stats = await get_stock_overview_stats(db)
    assert stats['order_regular_quantity'] == 3
    assert stats['order_custom_quantity'] == 2
    assert stats['order_quantity'] == 5
    assert stats['stockin_quantity'] == 0


async def test_overview_stats_legacy_fallback(db, products_ab, mixed_order, legacy_order):
    """无明细订单回退订单级字段：regular = 3(明细) + 5(兼容) = 8"""
    stats = await get_stock_overview_stats(db)
    assert stats['order_regular_quantity'] == 8
    assert stats['order_custom_quantity'] == 2


async def test_fetch_inventory_per_sku(db, products_ab, mixed_order, legacy_order):
    """库存聚合按 SKU 拆分：A 得 regular=8（明细3+兼容5），B 得 custom=2 与国家归属

    注：_merge_inventory_rows 中由订单聚合创建的行不带 product_id 键（既有行为），
    故按 product_barcode 匹配。
    """
    rows = await _fetch_inventory(db, None, cust=CUSTOMER)
    by_barcode = {r['product_barcode']: r for r in rows}
    assert by_barcode['MSKU-A']['regular_order_qty'] == 8
    assert by_barcode['MSKU-A']['custom_order_qty'] == 0
    # 旧实现按 o.product_id 分组，B 产品完全不出现在库存视图
    assert by_barcode['MSKU-B']['custom_order_qty'] == 2
    assert by_barcode['MSKU-B']['country_data'] == '法国:2'


async def test_stockouts_type_from_matched_item(db, products_ab, mixed_order):
    """出库 B 产品（定制明细）：order_type/country 取匹配明细而非订单首 item 兼容值"""
    db.add(StockOut(
        stockout_no='MSKU-SO-001', stockout_date=datetime.now(UTC),
        product_id=products_ab[1].id, customer=CUSTOMER, quantity=1,
        order_id=mixed_order.id,
    ))
    await db.flush()
    result = await get_stockouts(db, customer=CUSTOMER)
    assert result['total'] == 1
    row = result['items'][0]
    assert row['order_type'] == 'custom'
    assert row['country'] == '法国'
