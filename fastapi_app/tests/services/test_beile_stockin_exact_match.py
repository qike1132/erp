"""D-R2-1 / D-R2-2 回归：stockin 精确（带类型）匹配，模糊匹配不得产出数量。

背景：beile 备货行原用 ``(customer, product_name)`` **模糊**匹配 completed 采购单并取
``MAX(product_quantity)`` 当作该备货的数量，会跨来源过度命中 → 编造数字（如把 969461
当成自身 10000 的数量，页面显示被放大 ~97×）。修复后：

- 备货**有**精确逐 SKU 行（``purchase_order_sku.source_record_type='stockin'``）→
  取该**精确集合**的汇总；
- 备货**无**精确逐 SKU 行 → 模糊匹配**只决定 ``is_ordered`` 信号**，数量一律 ``None``；
- order 路径口径 **零变化**（一张 PO 覆盖多张订单时各订单取自身汇总）。

本文件独立于 QA 作者的 ``test_qa_*`` 文件，不与其重叠。
"""
from datetime import datetime

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from fastapi_app.services.order.beile import (
    _apply_ordered_fields,
    get_beile_orders_with_stockins,
)
from fastapi_app.shared_models import (
    Base,
    Order,
    OrderItem,
    Product,
    PurchaseOrder,
    PurchaseOrderSku,
    PurchaseOrderStatus,
    StockIn,
    User,
)


@pytest_asyncio.fixture(autouse=True)
def _isolate_cache(monkeypatch):
    """隔离进程内缓存：前后各清一次，避免本文件内/跨文件用例互相污染。

    `get_beile_orders_with_stockins` 受 `@cache_result` 装饰，同 key
    （page/per_page/customer/factory/confirm_status/product_kw 相同）会在进程内命中；
    每个测试用独立内存库，故必须在每个测试前后失效缓存。
    """
    from fastapi_app.core import cache as cache_module

    monkeypatch.setattr(cache_module, '_get_redis_cache', lambda: None)
    cache_module.invalidate_local_cache('*')
    yield
    cache_module.invalidate_local_cache('*')


@pytest_asyncio.fixture
async def db():
    """真实模型的 sqlite 内存库会话（每测试独立实例）。

    必须包含 PurchaseOrderSku（精确逐 SKU 匹配依赖它）与 StockIn。
    """
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    tables = [
        User.__table__, Product.__table__, Order.__table__,
        OrderItem.__table__, StockIn.__table__,
        PurchaseOrder.__table__, PurchaseOrderSku.__table__,
    ]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    maker = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


def _user() -> User:
    return User(id=1, username='op', password='x', factory='湖北')


# =========================================================================
# D1：模糊 pos 但无精确逐 SKU 行 → 数量一律 None，is_ordered 保留
# =========================================================================
async def test_stockin_fuzzy_only_produces_no_quantity(db):
    """备货有模糊 pos 但无精确逐 SKU 行 ⇒ None/None，is_ordered=True。"""
    p = Product(id=1, name='变形金刚', barcode='bT', factory='湖北')
    s = StockIn(id=21, stockin_no='SI-021', customer='客户C', product_id=1,
                quantity=10000, stockin_date=datetime(2026, 9, 2, 10, 0))
    # 模糊命中：customer/product 一致，但 product_quantity=969461 属**跨来源**过度命中
    po = PurchaseOrder(id=20397, order_no='CG-20397', status=PurchaseOrderStatus.COMPLETED,
                       supplier_name='供应商甲', source_order_ids='[68740]',
                       customer_name='客户C', product_name='变形金刚',
                       product_quantity=969461, spare_quantity=10665, spare_rate=50)
    db.add_all([_user(), p, s, po])
    await db.commit()

    result = await get_beile_orders_with_stockins(db, page=1, per_page=50)
    row = next(r for r in result['items'] if r['record_type'] == 'stockin' and r['id'] == 21)

    assert row['is_ordered'] is True
    # 核心：模糊匹配不得把 MAX(product_quantity)=969461 当成该备货自己的数量
    assert row['purchase_order_qty'] is None
    assert row['spare_quantity'] is None
    assert row['spare_rate'] == 50  # 仅作展示提示，不代表准确损耗率

    item = row['items'][0]
    assert item['per_sku_source'] == 'order_level'
    assert item['purchase_order_qty'] is None, '降级时逐 SKU 不得编造数字'
    assert item['spare_quantity'] is None


# =========================================================================
# D2：有精确逐 SKU 行且其 po_id 集合与模糊集合不同 → 采用精确集合汇总
# =========================================================================
async def test_stockin_exact_rows_win_over_fuzzy_max(db):
    """备货有精确逐 SKU 行（po 20352=10000），模糊集合另有 MAX=12424 ⇒ 采用精确。"""
    p = Product(id=1, name='Nommi盲盒', barcode='bN', factory='湖北')
    s = StockIn(id=21, stockin_no='SI-021', customer='MINISO国内', product_id=1,
                quantity=10000, stockin_date=datetime(2026, 9, 3, 10, 0))
    # 精确来源采购单：以该备货为 source（stockin, 21）—— order_qty=10000
    po_exact = PurchaseOrder(id=20352, order_no='CG-20352', status=PurchaseOrderStatus.COMPLETED,
                             supplier_name='供应商甲', customer_name='MINISO国内',
                             product_name='Nommi盲盒', product_quantity=10000)
    # 模糊命中但非该备货来源的采购单：MAX(product_quantity)=12424（D-R2-2 的成因）
    po_fuzzy = PurchaseOrder(id=20351, order_no='CG-20351', status=PurchaseOrderStatus.COMPLETED,
                             supplier_name='供应商乙', customer_name='MINISO国内',
                             product_name='Nommi盲盒', product_quantity=12424)
    sku = PurchaseOrderSku(po_id=20352, product_name='Nommi盲盒', order_qty=10000, spare_qty=0,
                           source_order_id=21, source_record_type='stockin')
    db.add_all([_user(), p, s, po_exact, po_fuzzy, sku])
    await db.commit()

    result = await get_beile_orders_with_stockins(db, page=1, per_page=50)
    row = next(r for r in result['items'] if r['record_type'] == 'stockin' and r['id'] == 21)

    assert row['is_ordered'] is True
    assert row['purchase_order_qty'] == 10000, '应采用精确逐 SKU 汇总，而非模糊 MAX=12424'
    assert row['spare_quantity'] == 0

    item = row['items'][0]
    assert item['per_sku_source'] == 'po_sku'
    assert item['purchase_order_qty'] == 10000


# =========================================================================
# D3：order 路径回归 —— 一张 PO 覆盖多张订单，各订单取自身数量
# =========================================================================
async def test_order_path_po_covers_many_orders_no_change(db):
    """order 路径回归：一张 PO 覆盖两张订单 ⇒ 各订单取自身逐 SKU 汇总（RC-2 口径不变）。"""
    pA = Product(id=1, name='A', barcode='bA', factory='湖北')
    pB = Product(id=2, name='B', barcode='bB', factory='湖北')
    o11 = Order(id=11, order_no='PO-011', customer='客户A', order_date=datetime(2026, 9, 1),
                product_id=1, quantity=10,
                items=[OrderItem(product_id=1, product_name='A', product_barcode='bA', quantity=10)])
    o12 = Order(id=12, order_no='PO-012', customer='客户B', order_date=datetime(2026, 9, 2),
                product_id=2, quantity=20,
                items=[OrderItem(product_id=2, product_name='B', product_barcode='bB', quantity=20)])
    po = PurchaseOrder(id=203, order_no='CPO-203', status=PurchaseOrderStatus.COMPLETED,
                       supplier_name='供应商甲', source_order_ids='[11,12]',
                       customer_name='客户A', product_name='A、B', product_quantity=30)
    skus = [
        PurchaseOrderSku(po_id=203, product_name='A', order_qty=10, spare_qty=1,
                         source_order_id=11, source_record_type='order'),
        PurchaseOrderSku(po_id=203, product_name='B', order_qty=20, spare_qty=2,
                         source_order_id=12, source_record_type='order'),
    ]
    db.add_all([_user(), pA, pB, o11, o12, po, *skus])
    await db.commit()

    result = await get_beile_orders_with_stockins(db, page=1, per_page=50)
    by_id = {r['id']: r for r in result['items'] if r['record_type'] == 'order'}

    assert by_id[11]['is_ordered'] is True
    assert by_id[12]['is_ordered'] is True
    # 修复前会把 MAX(product_quantity)=30 注入两张订单（系统性高估）
    assert by_id[11]['purchase_order_qty'] == 10
    assert by_id[12]['purchase_order_qty'] == 20


# =========================================================================
# D4：_apply_ordered_fields(pos_exact=False) 不得产出任何非 None 数量
# =========================================================================
def test_apply_ordered_fields_pos_exact_false_yields_no_quantities():
    """单元契约：pos_exact=False 时 purchase_order_qty / spare_quantity 一律 None。"""

    class _Po:
        id = 1
        product_quantity = 969461
        spare_quantity = 10665
        spare_rate = 50

    record = {
        'quantity': 10000,
        'is_ordered': False,
        'items': [{'product_name': '变形金刚', 'quantity': 10000}],
    }
    out = _apply_ordered_fields(record, [_Po()], sku_rows=[], pos_exact=False)

    assert out['is_ordered'] is True
    assert out['purchase_order_qty'] is None
    assert out['spare_quantity'] is None
    assert out['spare_rate'] == 50  # 仍保留模糊命中的 max（仅作展示提示）
    assert out['items'][0]['purchase_order_qty'] is None
    assert out['items'][0]['spare_quantity'] is None


def test_apply_ordered_fields_pos_exact_true_keeps_max_fallback():
    """对照：pos_exact=True（默认/order 路径）仍保留 MAX 回退口径，行为不变。"""

    class _Po:
        id = 1
        product_quantity = 969461
        spare_quantity = 10665
        spare_rate = 50

    record = {
        'quantity': 10000,
        'is_ordered': False,
        'items': [{'product_name': '变形金刚', 'quantity': 10000}],
    }
    out = _apply_ordered_fields(record, [_Po()], sku_rows=[], pos_exact=True)

    assert out['is_ordered'] is True
    assert out['purchase_order_qty'] == 969461  # 订单路径既有口径：无逐 SKU 行 → MAX
    assert out['spare_quantity'] == 10665
