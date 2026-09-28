"""多 SKU 库存统计集成测试（A 类统计改造，2026-08-22）

验证 OrderItem 维度聚合的正确性：
- 混合 SKU 订单按明细累加统计
- 无明细兼容订单（批量导入路径）回退订单级字段（COALESCE）
- 库存聚合按 SKU 维度拆分

复用根 conftest 的会话级 test_engine（loop_scope="session" 已修复
ScopeMismatch），事务回滚隔离，只写测试库 erp_system_test。
"""
import os
from datetime import UTC, datetime
from urllib.parse import urlparse, urlunparse

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fastapi_app.services.stock_inventory_service import (
    _fetch_inventory,
    get_inventory_paginated,
    get_stock_overview_stats,
)
from fastapi_app.shared_models import Order, OrderItem, Product

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
async def db(test_engine):
    """函数级测试会话：复用会话级引擎 + 事务回滚隔离。

    早期版本因 ScopeMismatch 自建函数级引擎并整库重置；
    test_engine 增加 loop_scope="session" 后可直接复用，
    避免每测试反复建/拆引擎与 DROP SCHEMA 引发的连接抖动。
    """
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False,
    )
    async with factory() as session:
        async with session.begin() as transaction:
            yield session
            await transaction.rollback()


@pytest_asyncio.fixture
async def committed_stats(test_engine):
    """在独立会话上读取全局统计——不含本测试未提交的数据。

    get_stock_overview_stats 是全局聚合（无客户/产品过滤），全量跑套件时
    其它用例已提交的订单会污染断言，故用增量比较。
    """
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False,
    )
    async with factory() as session:
        return await get_stock_overview_stats(session)


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
    """混合 SKU 订单：A 产品 3 件 + B 产品 2 件。

    订单级兼容字段故意写成首 item 值（product_id=A / quantity=5），
    旧实现在此数据下统计错误，新实现应按明细得出 3/2。
    """
    order = Order(
        order_no='MSKU-MIX-001', customer=CUSTOMER, order_date=datetime.now(UTC),
        product_id=products_ab[0].id, quantity=5, status='待备货',
    )
    db.add(order)
    await db.flush()
    db.add(OrderItem(
        order_id=order.id, product_id=products_ab[0].id, quantity=3))
    db.add(OrderItem(
        order_id=order.id, product_id=products_ab[1].id, quantity=2))
    await db.flush()
    return order


@pytest.fixture
async def legacy_order(db, products_ab):
    """无明细兼容订单（模拟批量导入路径）：A 产品 5 件。"""
    order = Order(
        order_no='MSKU-LEG-001', customer=CUSTOMER, order_date=datetime.now(UTC),
        product_id=products_ab[0].id, quantity=5, status='待备货',
    )
    db.add(order)
    await db.flush()
    return order


@pytest.fixture
async def deleted_order(db, products_ab):
    """软删除订单：删除只置 is_deleted=TRUE，行仍留在 order 表中。"""
    order = Order(
        order_no='MSKU-DEL-001', customer=CUSTOMER, order_date=datetime.now(UTC),
        product_id=products_ab[0].id, quantity=10000, status='待备货',
    )
    db.add(order)
    await db.flush()
    order.is_deleted = True
    await db.flush()
    return order


async def test_overview_stats_item_dimension(db, products_ab, mixed_order, committed_stats):
    """混合 SKU 订单：订单数量按明细累加（旧实现会得出 5/0 的分类）"""
    stats = await get_stock_overview_stats(db)
    assert stats['order_quantity'] - committed_stats['order_quantity'] == 5
    assert stats['stockin_quantity'] - committed_stats['stockin_quantity'] == 0


async def test_overview_stats_legacy_fallback(
        db, products_ab, mixed_order, legacy_order, committed_stats):
    """无明细订单回退订单级字段：5(明细) + 5(兼容) = 10"""
    stats = await get_stock_overview_stats(db)
    assert stats['order_quantity'] - committed_stats['order_quantity'] == 10


async def test_fetch_inventory_per_sku(db, products_ab, mixed_order, legacy_order):
    """库存聚合按 SKU 拆分：A 得 8（明细3+兼容5），B 得 2

    注：_merge_inventory_rows 中由订单聚合创建的行不带 product_id 键（既有行为），
    故按 product_barcode 匹配。
    """
    rows = await _fetch_inventory(db, None, cust=CUSTOMER)
    by_barcode = {r['product_barcode']: r for r in rows}
    assert by_barcode['MSKU-A']['order_qty'] == 8
    # 旧实现按 o.product_id 分组，B 产品完全不出现在库存视图
    assert by_barcode['MSKU-B']['order_qty'] == 2


async def test_deleted_order_excluded_from_inventory_legacy(
        db, products_ab, mixed_order, deleted_order):
    """软删除订单不计入库存聚合（回归：删除订单后 /stock 仍显示其数量）。

    旧实现的订单/国家聚合 SQL 只有 WHERE 1=1，没有 is_deleted 过滤，
    已删订单（10000 件）会永久留在库存视图里。
    """
    rows = await _fetch_inventory(db, None, cust=CUSTOMER)
    by_barcode = {r['product_barcode']: r for r in rows}
    assert by_barcode['MSKU-A']['order_qty'] == 3
    assert by_barcode['MSKU-B']['order_qty'] == 2


async def test_deleted_order_excluded_from_inventory_paginated(
        db, products_ab, mixed_order, deleted_order):
    """/stock 实际走的 CTE 分页查询同样必须排除软删除订单。

    直接调用被 @cache_result 包装的实现体（__wrapped__），避免测试污染真实 Redis 缓存。
    """
    result = await get_inventory_paginated.__wrapped__(
        db, search_customer=CUSTOMER, page=1, per_page=50)
    by_name = {r['product_name']: r for r in result['inventory_data']}
    assert by_name['多SKU产品A']['order_quantity'] == 3
    assert by_name['多SKU产品B']['order_quantity'] == 2
    assert result['total_order_qty'] == 5
