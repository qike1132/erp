"""客户快捷切换栏的成员口径（/stock 页面顶部客户 chips）——集成测试。

背景（2026-09-30 线上报障）：`/stock` 表格里能看见 `MINISO国际`（该客户只有
1 条备货 10000 件，10 条订单全部软删除），但顶部客户快捷切换栏里没有它 ——
看得见、却筛不了。

根因：`_get_all_customers` 曾只读 `order` 表（“只放有订单数量的客户”），
而表格行来自 stock_in ⟗ stock_out ⟗ order 三表合并，两者口径不一致：
凡“只有备货、没有有效订单”的客户都会从切换栏里漏掉。

这里锁定修复后的口径（与表格行口径对齐）：
- 成员 = 出现在 stock_in 或「未软删的 order」里的客户；
- 只被软删订单提到的客户不算（表格也不显示这类客户）；
- 排序仍按最近活动倒序（最近下单/备货的客户置顶）。

复用根 conftest 的会话级 test_engine，只写测试库 erp_system_test。
"""
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fastapi_app.services import stock_inventory_service as svc
from fastapi_app.services.stock_inventory_service import _get_all_customers
from fastapi_app.shared_models import Order, Product, StockIn

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def db(test_engine):
    """函数级测试会话：复用会话级引擎 + 事务回滚隔离（与 test_multi_sku_inventory_stats 同款）。"""
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False,
    )
    async with factory() as session:
        async with session.begin() as transaction:
            yield session
            await transaction.rollback()

# 用互不相同的名字，避免全量跑套件时被其它用例提交的数据干扰
ONLY_STOCKIN = '仅备货客户-切栏'
HAS_ORDER = '有订单客户-切栏'
ONLY_DELETED_ORDER = '仅已删订单客户-切栏'
BAR_PRODUCT_BARCODE = 'BAR-CUST-001'


@pytest.fixture
async def bar_product(db):
    product = Product(
        name='切栏测试产品', barcode=BAR_PRODUCT_BARCODE,
        current_stock=0, initial_stock=0,
    )
    db.add(product)
    await db.flush()
    return product


@pytest.fixture
async def stockin_only_customer(db, bar_product):
    """只有备货、没有任何订单的客户：备货日期取 30 天前（用于排序断言）。"""
    db.add(StockIn(
        stockin_no='BAR-SI-001', product_id=bar_product.id, customer=ONLY_STOCKIN,
        quantity=10000, stockin_date=datetime.now(UTC) - timedelta(days=30),
    ))
    await db.flush()
    return ONLY_STOCKIN


@pytest.fixture
async def ordered_customer(db, bar_product):
    """有未删除订单的客户：下单时间为此刻（用于排序断言）。"""
    db.add(Order(
        order_no='BAR-ORD-001', customer=HAS_ORDER, product_id=bar_product.id,
        quantity=5, order_date=datetime.now(UTC), status='待备货',
    ))
    await db.flush()
    return HAS_ORDER


@pytest.fixture
async def deleted_order_only_customer(db, bar_product):
    """只被软删订单提到的客户：表格不显示，切换栏也不应出现。"""
    order = Order(
        order_no='BAR-ORD-DEL-001', customer=ONLY_DELETED_ORDER,
        product_id=bar_product.id, quantity=9999,
        order_date=datetime.now(UTC), status='待备货',
    )
    db.add(order)
    await db.flush()
    order.is_deleted = True
    await db.flush()
    return ONLY_DELETED_ORDER


async def test_stockin_only_customer_appears_in_bar(db, bar_product, stockin_only_customer):
    """只有备货、没有有效订单的客户必须在切换栏里（线上报障的直接回归）。

    旧实现只查 order 表，该客户不在结果里；而库存表格里明明有它的行。
    """
    names = await _get_all_customers.__wrapped__(db, None)
    assert ONLY_STOCKIN in names


async def test_deleted_order_only_customer_absent_from_bar(
        db, bar_product, deleted_order_only_customer):
    """只被软删订单提到的客户不进切换栏（软删订单不计入表格，也不该给 chip）。"""
    names = await _get_all_customers.__wrapped__(db, None)
    assert ONLY_DELETED_ORDER not in names


async def test_bar_orders_by_recent_activity(
        db, bar_product, stockin_only_customer, ordered_customer):
    """排序口径不变：最近有活动的客户排前面（有订单客户此刻下单，排在 30 天前备货的客户之前）。"""
    names = await _get_all_customers.__wrapped__(db, None)
    assert ONLY_STOCKIN in names and HAS_ORDER in names
    assert names.index(HAS_ORDER) < names.index(ONLY_STOCKIN)


async def test_inventory_end_to_end_carries_stockin_only_customer(
        db, bar_product, stockin_only_customer, ordered_customer, monkeypatch):
    """/stock 实际走的 get_inventory_paginated 必须把该客户带进 all_customers。

    两层都要绕开缓存：外层用 __wrapped__ 直接调实现体；内层客户列表被
    @cache_result(ttl=120) 包着，同进程里先跑过的库存用例已把 'all' 键填成
    它自己的客户（会话回滚了但缓存还在），故这里换成未包装的原始函数。
    """
    monkeypatch.setattr(svc, '_get_all_customers', _get_all_customers.__wrapped__)
    result = await svc.get_inventory_paginated.__wrapped__(
        db, search_customer='', page=1, per_page=200)
    assert ONLY_STOCKIN in result['all_customers']
    assert HAS_ORDER in result['all_customers']


async def test_bar_passes_product_filter_to_both_sources(
        db, bar_product, monkeypatch):
    """按产品搜索时，客户列表沿用产品过滤（备货/订单两个来源都过滤）。"""
    captured = {}

    async def _fake(db_, pids, factory=''):
        captured['pids'] = pids
        captured['factory'] = factory
        return ['X']

    monkeypatch.setattr(svc, '_get_all_customers', _fake)
    result = await svc.get_inventory_paginated.__wrapped__(
        db, search_product='切栏测试产品', page=1, per_page=200)
    assert result['all_customers'] == ['X']
    assert captured['pids'] == (bar_product.id,)
    assert captured['factory'] == ''


async def test_bar_wiring_uses_customer_query_result(db, monkeypatch):
    """接线断言：all_customers 直接来自 _get_all_customers 的返回值（不做二次裁剪）。"""
    monkeypatch.setattr(svc, '_get_all_customers', AsyncMock(return_value=['甲', '乙']))
    result = await svc.get_inventory_paginated.__wrapped__(
        db, search_customer='', page=1, per_page=5)
    assert result['all_customers'] == ['甲', '乙']
