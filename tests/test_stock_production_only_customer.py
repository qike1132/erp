"""库存页「只有生产记录的产品」客户显示回归测试（2026-11-01 线上报障）。

现象：录入生产数据（选了客户、2424 件）后，/stock 库存页该产品行的「客户」为空。
根因：库存 CTE 的 `packaging_production_products` 只带 product_id，没有客户维度；
凡「只有包装部生产、没有订单/备货/出库」的产品，库存行 `customer` 落到 COALESCE 的
空串兜底，于是显示空白。客户快捷栏同样漏掉这类客户（看得见、筛不了）。

本用例锁定修复后的口径：
- 生产行必须带出生产记录上的客户名；
- 按该客户筛选时这一行仍在；
- 客户快捷栏成员包含该客户。

复用根 conftest 的会话级 test_engine，事务回滚隔离，只写测试库 erp_system_test。
"""
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fastapi_app.services.stock_inventory_service import (
    _get_all_customers,
    get_inventory_paginated,
)
from fastapi_app.shared_models import DailyProductionRecord, Product

pytestmark = pytest.mark.integration

# 名字带后缀，避免与全量套件里其它用例的数据互相干扰
PROD_CUSTOMER = '只录生产客户-回归1101'
PRODUCT_NAME = 'Nommi回归产品-1101'
PRODUCT_BARCODE = 'REGR-1101-0001'
QTY = 2424


@pytest_asyncio.fixture
async def db(test_engine):
    """函数级测试会话：复用会话级引擎 + 事务回滚隔离。"""
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False,
    )
    async with factory() as session:
        async with session.begin() as transaction:
            yield session
            await transaction.rollback()


@pytest_asyncio.fixture
async def production_only_product(db):
    """建一个「只有包装部生产记录、没有订单/备货」的产品。"""
    product = Product(
        name=PRODUCT_NAME, barcode=PRODUCT_BARCODE,
        current_stock=0, initial_stock=0,
    )
    db.add(product)
    await db.flush()

    db.add(DailyProductionRecord(
        department='packaging',
        product_id=product.id,
        customer_id=None,
        customer_name=PROD_CUSTOMER,
        product_name=PRODUCT_NAME,
        barcode=PRODUCT_BARCODE,
        unit_price=Decimal('0'),
        quantity=QTY,
        production_date=date.today(),
    ))
    await db.flush()
    return product


@pytest.mark.asyncio
async def test_production_only_row_keeps_customer(db, production_only_product):
    """只有生产记录的产品，库存行必须显示客户（不能是空白）。

    走 __wrapped__ 绕开 @cache_result：同进程里别的用例/接口可能已经缓存过
    同一查询键，不绕开就会命中旧缓存（假通过）或旧数据（假失败）。
    """
    result = await get_inventory_paginated.__wrapped__(db, search_product=PRODUCT_NAME)

    rows = [r for r in result['inventory_data'] if r['product_name'] == PRODUCT_NAME]
    assert rows, '生产记录应该在库存页成行'

    row = rows[0]
    assert row['customer'] == PROD_CUSTOMER, '客户不能为空：生产记录的客户名要带出来'
    assert row['inventory_balance'] == QTY, '包装部入库应计入库存结余'


@pytest.mark.asyncio
async def test_production_only_row_survives_customer_filter(db, production_only_product):
    """按该客户筛选时，这一行仍然出现（此前会被 :sc_is_empty 条件整行滤掉）。"""
    result = await get_inventory_paginated.__wrapped__(db, search_customer=PROD_CUSTOMER)

    names = [r['product_name'] for r in result['inventory_data']]
    assert PRODUCT_NAME in names


@pytest.mark.asyncio
async def test_customer_bar_contains_production_customer(db, production_only_product):
    """客户快捷栏要包含「只在生产记录里出现」的客户，否则看得见却筛不了。"""
    customers = await _get_all_customers.__wrapped__(db, None)
    assert PROD_CUSTOMER in customers
