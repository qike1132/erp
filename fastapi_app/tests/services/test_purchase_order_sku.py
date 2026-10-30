"""方案 C 逐 SKU 数量快照（purchase_order_sku）写/读/降级回归。

覆盖（对应交付范围 A–E 的后端部分）：
- build_po_sku_rows：多 SKU 拆分；同一来源同产品名多行**合并**（不拆分/不摊派）；备品按率计算。
- write_po_sku_rows / po_sku_available：表缺失时**优雅降级**（返回 0 且不抛错）。
- resync_po_sku_spare：损耗率变更后按新率重算逐 SKU 备品。
- /beile-list 逐 SKU 注入：命中快照 → per_sku_source='po_sku'、逐 SKU 订单数量/备品数量。
- RC-2 回归：一张采购单覆盖多张订单时，各订单显示「自己」的 Σ，而非采购单合计 MAX（系统性高估）。
- delete_purchase_order：级联清理逐 SKU 行（SQLite 未开外键约束下也不留孤儿行）。

使用 sqlite+aiosqlite 内存库 + 真实模型（含 purchase_order_sku）。
"""
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from fastapi_app.services.order.beile import get_beile_orders_with_stockins
from fastapi_app.services.purchase_order_crud import delete_purchase_order
from fastapi_app.services.purchase_order_sku import (
    build_po_sku_rows,
    po_sku_available,
    resync_po_sku_spare,
    write_po_sku_rows,
)
from fastapi_app.shared_models import (
    Base,
    MaterialRegistration,
    MaterialRegistrationItem,
    Order,
    OrderItem,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderSku,
    PurchaseOrderStatus,
    StockIn,
    User,
)

_CORE_TABLES = [
    User.__table__, Product.__table__, Order.__table__,
    OrderItem.__table__, StockIn.__table__, PurchaseOrder.__table__,
    PurchaseOrderItem.__table__,
    # PurchaseOrder 反向引用了 MaterialRegistration（backref="registrations"）：
    # db.delete(order) 会为无级联配置的关系置空外键，需要该表存在
    MaterialRegistration.__table__, MaterialRegistrationItem.__table__,
]


@pytest.fixture(autouse=True)
def _isolate_cache(monkeypatch):
    """隔离缓存：禁用 L2(Redis) 并清空 L1。

    `/beile-list` 带 L2 缓存（ttl=60s），其 key 只含 page/per_page/筛选，不含数据指纹；
    若本模块与其它测试/真实实例共用同一 Redis，不同 seed 的相同 key 会互相污染
    （local_ttl=0 只关 L1，不关 L2）。禁用 L2 使本模块测试自洽、也不反向污染真实缓存。
    """
    from fastapi_app.core import cache as cache_module
    monkeypatch.setattr(cache_module, '_get_redis_cache', lambda: None)
    cache_module.invalidate_local_cache('*')
    yield


async def _make_session(include_sku: bool):
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    tables = list(_CORE_TABLES)
    if include_sku:
        tables.append(PurchaseOrderSku.__table__)
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    maker = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    return engine, maker


@pytest_asyncio.fixture
async def db():
    """含 purchase_order_sku 表的内存库（迁移已执行视角）。"""
    engine, maker = await _make_session(include_sku=True)
    async with maker() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def db_no_sku():
    """**不含** purchase_order_sku 表的内存库（迁移未执行视角）。"""
    engine, maker = await _make_session(include_sku=False)
    async with maker() as session:
        yield session
    await engine.dispose()


# =========================================================================
# 纯函数：build_po_sku_rows
# =========================================================================
def test_build_po_sku_rows_splits_skus_and_merges_same_product():
    order = Order(id=11)
    order.items = [
        OrderItem(product_id=1, product_name='A', product_barcode='bA', quantity=10),
        OrderItem(product_id=2, product_name='B', product_barcode='bB', quantity=20),
        OrderItem(product_id=1, product_name='A', product_barcode='bA', quantity=5),
    ]
    rows = build_po_sku_rows([order], spare_rate=50)

    by_name = {r['product_name']: r for r in rows}
    assert set(by_name) == {'A', 'B'}
    # 同一来源同产品名的多行合并（10 + 5），不拆分/不摊派
    assert by_name['A']['order_qty'] == 15
    assert by_name['A']['spare_qty'] == 1  # ceil(15*50/1000)=ceil(0.75)=1（字面量期望，防镜像断言）
    assert by_name['B']['order_qty'] == 20
    assert by_name['B']['spare_qty'] == 1  # ceil(20*50/1000)=1
    assert all(r['source_order_id'] == 11 and r['source_record_type'] == 'order' for r in rows)
    assert all(r['spare_rate'] == 50 for r in rows)


def test_build_po_sku_rows_without_rate_spare_is_zero():
    order = Order(id=12)
    order.items = [OrderItem(product_id=1, product_name='A', product_barcode='bA', quantity=7)]
    rows = build_po_sku_rows([order], spare_rate=None)
    assert rows[0]['order_qty'] == 7
    assert rows[0]['spare_qty'] == 0  # rate=None → 0
    assert rows[0]['spare_rate'] is None


# =========================================================================
# 优雅降级：表缺失
# =========================================================================
async def test_po_sku_available_false_and_cached_when_table_missing(db_no_sku):
    assert await po_sku_available(db_no_sku) is False
    # db.info 缓存：二次调用不再探测（不抛错）
    assert await po_sku_available(db_no_sku) is False


async def test_write_po_sku_rows_returns_zero_without_table(db_no_sku):
    order = Order(id=11)
    order.items = [OrderItem(product_id=1, product_name='A', product_barcode='bA', quantity=10)]
    written = await write_po_sku_rows(db_no_sku, 999, [order], spare_rate=None)
    assert written == 0  # 表缺失 → 跳过落库，不抛错（代码先于迁移部署不中断下单）


async def test_beile_read_degrades_without_sku_table(db_no_sku):
    """表缺失时 /beile-list 仍可读，回退订单级 MAX 口径、逐 SKU 标记为 order_level。"""
    user = User(id=1, username='op', password='x', factory='湖北')
    product = Product(id=1, name='A', barcode='bA', factory='湖北')
    order = Order(
        id=11, order_no='PO-011', customer='客户A', order_date=datetime(2026, 9, 1, 10, 0, 0),
        product_id=1, quantity=10000,
        items=[OrderItem(product_id=1, product_name='A', product_barcode='bA', quantity=10000)],
    )
    po = PurchaseOrder(id=201, order_no='CPO-201', status=PurchaseOrderStatus.COMPLETED,
                       source_order_ids='[11]', customer_name='客户A', product_name='A',
                       product_quantity=10000)
    db_no_sku.add_all([user, product, order, po])
    await db_no_sku.commit()

    result = await get_beile_orders_with_stockins(db_no_sku, page=1, per_page=50)
    row = next(r for r in result['items'] if r['record_type'] == 'order' and r['id'] == 11)
    assert row['is_ordered'] is True
    assert row['purchase_order_qty'] == 10000  # 回退 MAX 口径
    assert row['items'][0]['per_sku_source'] == 'order_level'
    assert row['items'][0]['purchase_order_qty'] is None


# =========================================================================
# 写路径：resync_po_sku_spare / delete 级联
# =========================================================================
async def test_resync_po_sku_spare_recomputes_by_new_rate(db):
    po = PurchaseOrder(id=201, order_no='CPO-201', status=PurchaseOrderStatus.COMPLETED,
                       source_order_ids='[11]', customer_name='客户A', product_name='A',
                       product_quantity=20)
    db.add_all([
        po,
        PurchaseOrderSku(po_id=201, product_name='A', order_qty=20, spare_qty=0,
                         source_order_id=11, source_record_type='order'),
    ])
    await db.commit()

    updated = await resync_po_sku_spare(db, [201], 50)
    assert updated == 1
    row = (await db.execute(select(PurchaseOrderSku))).scalars().one()
    assert row.spare_rate == 50
    assert row.spare_qty == 1  # ceil(20*50/1000)=1（字面量期望，防镜像断言）


async def test_resync_po_sku_spare_noop_when_rate_none(db):
    db.add(PurchaseOrderSku(po_id=201, product_name='A', order_qty=20, spare_qty=5,
                            source_order_id=11, source_record_type='order'))
    await db.commit()
    assert await resync_po_sku_spare(db, [201], None) == 0


async def test_delete_purchase_order_cascades_sku_rows(db):
    po = PurchaseOrder(id=201, order_no='CPO-201', status=PurchaseOrderStatus.COMPLETED,
                       source_order_ids='[11]', customer_name='客户A', product_name='A',
                       product_quantity=10)
    db.add_all([
        po,
        PurchaseOrderSku(po_id=201, product_name='A', order_qty=10, spare_qty=0,
                         source_order_id=11, source_record_type='order'),
    ])
    await db.commit()

    await delete_purchase_order(db, 201)

    assert await db.get(PurchaseOrder, 201) is None
    remaining = (await db.execute(select(PurchaseOrderSku))).scalars().all()
    assert remaining == [], '删除采购单必须级联清理逐 SKU 快照，不得残留孤儿行'


# =========================================================================
# 读路径：逐 SKU 注入 + RC-2 回归
# =========================================================================
async def _seed_two_orders_one_po(db):
    """o11: SKU A=10 / o12: SKU B=20；**一张** completed 采购单 203 覆盖两张订单，合计 30。"""
    user = User(id=1, username='op', password='x', factory='湖北')
    pA = Product(id=1, name='A', barcode='bA', factory='湖北')
    pB = Product(id=2, name='B', barcode='bB', factory='湖北')
    o11 = Order(id=11, order_no='PO-011', customer='客户A', order_date=datetime(2026, 9, 1, 10, 0, 0),
                product_id=1, quantity=10,
                items=[OrderItem(product_id=1, product_name='A', product_barcode='bA', quantity=10)])
    o12 = Order(id=12, order_no='PO-012', customer='客户B', order_date=datetime(2026, 9, 2, 10, 0, 0),
                product_id=2, quantity=20,
                items=[OrderItem(product_id=2, product_name='B', product_barcode='bB', quantity=20)])
    po = PurchaseOrder(id=203, order_no='CPO-203', status=PurchaseOrderStatus.COMPLETED,
                       source_order_ids='[11,12]', customer_name='客户A', product_name='A、B',
                       product_quantity=30)
    skus = [
        PurchaseOrderSku(po_id=203, product_name='A', order_qty=10, spare_qty=1,
                         source_order_id=11, source_record_type='order'),
        PurchaseOrderSku(po_id=203, product_name='B', order_qty=20, spare_qty=2,
                         source_order_id=12, source_record_type='order'),
    ]
    db.add_all([user, pA, pB, o11, o12, po, *skus])
    await db.commit()


async def test_rc2_one_po_covers_multiple_orders_no_overestimation(db):
    """RC-2 回归：一张采购单覆盖 N 张订单时，各订单显示自己的 Σ，而不是采购单合计 MAX。"""
    await _seed_two_orders_one_po(db)

    result = await get_beile_orders_with_stockins(db, page=1, per_page=50)
    by_id = {r['id']: r for r in result['items'] if r['record_type'] == 'order'}

    # 修复前：两张订单都会被注入 MAX(product_quantity)=30（系统性高估）
    assert by_id[11]['purchase_order_qty'] == 10
    assert by_id[12]['purchase_order_qty'] == 20
    assert by_id[11]['is_ordered'] is True
    assert by_id[12]['is_ordered'] is True

    # 逐 SKU 注入：命中快照 → per_sku_source='po_sku'，逐 SKU 订单数量/备品各自准确
    it11 = by_id[11]['items'][0]
    assert it11['per_sku_source'] == 'po_sku'
    assert it11['purchase_order_qty'] == 10
    assert it11['spare_quantity'] == 1
    assert it11['is_ordered'] is True

    it12 = by_id[12]['items'][0]
    assert it12['per_sku_source'] == 'po_sku'
    assert it12['purchase_order_qty'] == 20
    assert it12['spare_quantity'] == 2


async def test_read_multi_sku_single_order_rollup_equals_sum(db):
    """单订单多 SKU：订单级 purchase_order_qty = 逐 SKU 之和（按产品名 MAX 去重再求和）。"""
    user = User(id=1, username='op', password='x', factory='湖北')
    pA = Product(id=1, name='A', barcode='bA', factory='湖北')
    pC = Product(id=3, name='C', barcode='bC', factory='湖北')
    order = Order(
        id=11, order_no='PO-011', customer='客户A', order_date=datetime(2026, 9, 1, 10, 0, 0),
        product_id=1, quantity=30000,
        items=[
            OrderItem(product_id=1, product_name='A', product_barcode='bA', quantity=10000),
            OrderItem(product_id=3, product_name='C', product_barcode='bC', quantity=20000),
        ],
    )
    po = PurchaseOrder(id=201, order_no='CPO-201', status=PurchaseOrderStatus.COMPLETED,
                       source_order_ids='[11]', customer_name='客户A', product_name='A、C',
                       product_quantity=30000)
    skus = [
        PurchaseOrderSku(po_id=201, product_name='A', order_qty=10000, spare_qty=10,
                         source_order_id=11, source_record_type='order'),
        PurchaseOrderSku(po_id=201, product_name='C', order_qty=20000, spare_qty=20,
                         source_order_id=11, source_record_type='order'),
    ]
    db.add_all([user, pA, pC, order, po, *skus])
    await db.commit()

    result = await get_beile_orders_with_stockins(db, page=1, per_page=50)
    row = next(r for r in result['items'] if r['record_type'] == 'order' and r['id'] == 11)

    assert row['purchase_order_qty'] == 30000  # 10000 + 20000
    assert row['spare_quantity'] == 30  # 10 + 20
    per = {i['product_name']: i for i in row['items']}
    assert per['A']['purchase_order_qty'] == 10000
    assert per['A']['spare_quantity'] == 10
    assert per['C']['purchase_order_qty'] == 20000
    assert per['C']['spare_quantity'] == 20
    assert all(i['per_sku_source'] == 'po_sku' for i in row['items'])
