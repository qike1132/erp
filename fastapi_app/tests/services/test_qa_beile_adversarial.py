"""QA 对抗性验证（独立于工程师自测）：/beile-order 数量与备品同步。

覆盖（P0）：
- A. 缺陷可捕获性（配合外部源码变异实验，见报告）：
     * L1(local_ttl=0) 禁用机制
     * MAX 口径（非 sum）
     * 未下单门控（409）
- B. 关联精度：'[65091]' 不得被 order_id=6509 命中（禁 LIKE）；多元素 / 脏数据不抛异常
- C. 列表标记与确认门控同源（4 种组合 + spare_rate=0）
- D. NULL / 空值边界（spare_rate=None 不覆盖；save_factory_summary_edits 空 edits；NULL 归一）
- E. 缓存失效机制（fnmatch 证明、_invalidate_orders_cache 覆盖 beile、local_ttl=0 生效）

本文件仅使用 sqlite 内存库 + 真实模型，不接触生产库。
"""
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from fastapi_app.services.order.beile import (
    BEILE_NOT_ORDERED_DETAIL,
    confirm_beile_order,
    confirm_beile_stockin,
    get_beile_orders_with_stockins,
    get_beile_unconfirmed_count,
)
from fastapi_app.services.purchase_utils import parse_source_order_ids
from fastapi_app.core.exceptions import ConflictError
from fastapi_app.shared_models import (
    Base,
    MaterialRegistration,
    MaterialRegistrationItem,
    ModificationLog,
    Notification,
    Order,
    OrderItem,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderStatus,
    StockIn,
    User,
)


@pytest_asyncio.fixture
async def db():
    """独立 sqlite 内存库（真实模型），每个测试一个实例。"""
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    tables = [
        User.__table__, Product.__table__, Order.__table__,
        OrderItem.__table__, StockIn.__table__, Notification.__table__,
        PurchaseOrder.__table__, PurchaseOrderItem.__table__,
        MaterialRegistration.__table__, MaterialRegistrationItem.__table__,
        ModificationLog.__table__,
    ]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    maker = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _no_redis(monkeypatch):
    """强制 L2(Redis) 不可用：所有缓存测试只观察 L1 行为，避免真实网络抖动。"""
    from fastapi_app.core import cache as cache_module
    monkeypatch.setattr(cache_module, '_get_redis_cache', lambda: None)
    cache_module.invalidate_local_cache('*')
    yield


QA_USER = User(id=1, username='qa_op', password='x', factory='湖北')


def _user() -> User:
    """每个测试构造全新的登录用户持久化行（避免跨 session 复用同一 ORM 实例）。"""
    return User(id=1, username='qa_op', password='x', factory='湖北')


def _order(oid, no, customer, date, product, qty, **kw):
    return Order(
        id=oid, order_no=no, customer=customer, order_date=date,
        product_id=product.id, quantity=qty,
        items=[OrderItem(product_id=product.id, product_name=product.name,
                         product_barcode=product.barcode, quantity=qty)],
        **kw,
    )


# =========================================================================
# B. 关联精度：禁 LIKE，'[65091]' 不得命中 order_id=6509
# =========================================================================
async def test_qa_order_id_json_precision_no_like_trap(db):
    """completed PO source_order_ids='[65091]'：6509 必须未下单、65091 必须已下单。"""
    p = Product(id=1, name='变形金刚', barcode='690001', factory='湖北')
    o_short = _order(6509, 'PO-6509', '客户短号', datetime(2026, 9, 1), p, 100)
    o_long = _order(65091, 'PO-65091', '客户长号', datetime(2026, 9, 2), p, 200)
    po = PurchaseOrder(id=901, order_no='CPO-901', status=PurchaseOrderStatus.COMPLETED,
                       source_order_ids='[65091]', customer_name='客户长号', product_name='变形金刚',
                       product_quantity=200, spare_quantity=10, spare_rate=50)
    db.add_all([_user(), p, o_short, o_long, po])
    await db.commit()

    result = await get_beile_orders_with_stockins(db, page=1, per_page=50)
    by_id = {r['id']: r for r in result['items']}

    assert by_id[6509]['is_ordered'] is False, 'order_id=6509 被 [65091] 误命中（LIKE 陷阱）'
    assert by_id[6509]['purchase_order_qty'] == 100  # 未下单 → 保留原数量
    assert by_id[6509]['spare_quantity'] == 0

    assert by_id[65091]['is_ordered'] is True   # 正例：防止「一律判 False」的假绿
    assert by_id[65091]['purchase_order_qty'] == 200
    assert by_id[65091]['spare_quantity'] == 10

    # 门控与列表标记同源
    with pytest.raises(ConflictError) as exc:
        await confirm_beile_order(db, 6509, QA_USER)
    assert exc.value.status_code == 409
    assert exc.value.message == BEILE_NOT_ORDERED_DETAIL
    assert (await db.get(Order, 6509)).confirmed_at is None

    ok = await confirm_beile_order(db, 65091, QA_USER)
    assert ok['success'] is True
    assert (await db.get(Order, 65091)).confirmed_at is not None


@pytest.mark.parametrize('raw,expected', [
    ('[65091]', [65091]),
    ('[65091, 65092]', [65091, 65092]),
    ('[ 65091 ]', [65091]),
    ('', []),
    ('null', []),
    ('abc', []),
    ('{}', []),
    ('[1,"x"]', []),      # int('x') 失败 → 整体返回 []
    (None, []),
    ([65091, '65092'], [65091, 65092]),
])
def test_qa_parse_source_order_ids_semantics(raw, expected):
    """脏数据 / 多元素语义与 parse_source_order_ids 一致，不得抛异常。"""
    assert parse_source_order_ids(raw) == expected


async def test_qa_dirty_source_order_ids_do_not_crash_list(db):
    """完成单携带脏 source_order_ids 时，列表查询不得抛异常。"""
    p = Product(id=1, name='变形金刚', barcode='690001', factory='湖北')
    o = _order(11, 'PO-11', '客户A', datetime(2026, 9, 1), p, 5)
    pos = [
        PurchaseOrder(id=1, order_no='D1', status=PurchaseOrderStatus.COMPLETED,
                      source_order_ids='abc', customer_name='客户A', product_name='变形金刚',
                      product_quantity=5),
        PurchaseOrder(id=2, order_no='D2', status=PurchaseOrderStatus.COMPLETED,
                      source_order_ids='null', customer_name='客户A', product_name='变形金刚',
                      product_quantity=5),
        PurchaseOrder(id=3, order_no='D3', status=PurchaseOrderStatus.COMPLETED,
                      source_order_ids='', customer_name='客户A', product_name='变形金刚',
                      product_quantity=5),
        PurchaseOrder(id=4, order_no='D4', status=PurchaseOrderStatus.COMPLETED,
                      source_order_ids='[ 11 ]', customer_name='客户A', product_name='变形金刚',
                      product_quantity=5),
    ]
    db.add_all([_user(), p, o, *pos])
    await db.commit()

    result = await get_beile_orders_with_stockins(db, page=1, per_page=50)
    row = next(r for r in result['items'] if r['id'] == 11)
    # '[ 11 ]' 解析为 [11]，故仍判定已下单
    assert row['is_ordered'] is True
    assert row['purchase_order_qty'] == 5


# =========================================================================
# C. 列表标记与确认门控同源（4 组合 + spare_rate=0）
# =========================================================================
async def test_qa_gating_and_list_flag_same_source(db):
    """4 种组合 + spare_rate=0：列表 is_ordered 与 confirm 结果必须一致。"""
    p = Product(id=1, name='变形金刚', barcode='690001', factory='湖北')
    o_completed = _order(101, 'PO-101', 'C1', datetime(2026, 9, 1), p, 100)
    o_pending = _order(102, 'PO-102', 'C2', datetime(2026, 9, 2), p, 100)
    o_none = _order(103, 'PO-103', 'C3', datetime(2026, 9, 3), p, 100)
    o_multi = _order(104, 'PO-104', 'C4', datetime(2026, 9, 4), p, 100)
    o_zero = _order(105, 'PO-105', 'C5', datetime(2026, 9, 5), p, 100)

    pos = [
        PurchaseOrder(id=201, order_no='PC-201', status=PurchaseOrderStatus.COMPLETED,
                      source_order_ids='[101]', customer_name='C1', product_name='变形金刚',
                      product_quantity=10000, spare_quantity=500, spare_rate=50),
        PurchaseOrder(id=202, order_no='PP-202', status=PurchaseOrderStatus.PENDING,
                      source_order_ids='[102]', customer_name='C2', product_name='变形金刚',
                      product_quantity=10000),
        # 多供应商：两张 completed，同 qty/spare → MAX 不叠加（AC-8）
        # 注意：sqlite 下 uq_po_pending_dedup 退化为全表唯一（PG 专用 partial where 失效），
        # 故两张单必须用不同 supplier_name（与生产 uq 以 supplier_name 分桶的语义一致）。
        PurchaseOrder(id=203, order_no='PC-203a', status=PurchaseOrderStatus.COMPLETED,
                      supplier_name='供应商甲',
                      source_order_ids='[104]', customer_name='C4', product_name='变形金刚',
                      product_quantity=10000, spare_quantity=500, spare_rate=50),
        PurchaseOrder(id=204, order_no='PC-203b', status=PurchaseOrderStatus.COMPLETED,
                      supplier_name='供应商乙',
                      source_order_ids='[104]', customer_name='C4', product_name='变形金刚',
                      product_quantity=10000, spare_quantity=500, spare_rate=50),
        # spare_rate=0：备品 0 但仍是「合法已记录」，必须 is_ordered=True 且可确认
        PurchaseOrder(id=205, order_no='PC-205', status=PurchaseOrderStatus.COMPLETED,
                      source_order_ids='[105]', customer_name='C5', product_name='变形金刚',
                      product_quantity=2000, spare_quantity=0, spare_rate=0),
    ]
    db.add_all([_user(), p, o_completed, o_pending, o_none, o_multi, o_zero, *pos])
    await db.commit()

    # ---- 先断言列表标记 ----
    result = await get_beile_orders_with_stockins(db, page=1, per_page=50)
    by_id = {r['id']: r for r in result['items']}

    assert by_id[101]['is_ordered'] is True
    assert by_id[101]['purchase_order_qty'] == 10000
    assert by_id[101]['spare_quantity'] == 500

    assert by_id[102]['is_ordered'] is False, 'pending 不算已下单（Q4）'
    assert by_id[102]['purchase_order_qty'] == 100
    assert by_id[102]['spare_quantity'] == 0

    assert by_id[103]['is_ordered'] is False
    assert by_id[103]['purchase_order_qty'] == 100

    assert by_id[104]['is_ordered'] is True
    assert by_id[104]['purchase_order_qty'] == 10000, 'MAX 不叠加：不应为 20000'
    assert by_id[104]['spare_quantity'] == 500, 'MAX 不叠加：不应为 1000'

    assert by_id[105]['is_ordered'] is True, 'spare_rate=0 不得被当成未下单'
    assert by_id[105]['spare_quantity'] == 0
    assert by_id[105]['spare_rate'] == 0

    # ---- 再断言 confirm 门控与列表一致 ----
    assert (await confirm_beile_order(db, 101, QA_USER))['success'] is True
    assert (await confirm_beile_order(db, 104, QA_USER))['success'] is True
    assert (await confirm_beile_order(db, 105, QA_USER))['success'] is True

    for oid in (102, 103):
        with pytest.raises(ConflictError) as exc:
            await confirm_beile_order(db, oid, QA_USER)
        assert exc.value.status_code == 409
        assert exc.value.message == BEILE_NOT_ORDERED_DETAIL
        assert (await db.get(Order, oid)).confirmed_at is None


async def test_qa_stockin_gating_same_source(db):
    """备货行门控与列表标记同源：(customer, product_name) 精确匹配 completed。"""
    p = Product(id=1, name='变形金刚', barcode='690001', factory='湖北')
    s_ordered = StockIn(id=301, stockin_no='SI-301', customer='客户X', product_id=1,
                        quantity=30, stockin_date=datetime(2026, 9, 1))
    s_unordered = StockIn(id=302, stockin_no='SI-302', customer='客户Y', product_id=1,
                          quantity=30, stockin_date=datetime(2026, 9, 2))
    po = PurchaseOrder(id=401, order_no='PC-401', status=PurchaseOrderStatus.COMPLETED,
                       customer_name='客户X', product_name='变形金刚',
                       product_quantity=8888, spare_quantity=444, spare_rate=50)
    db.add_all([_user(), p, s_ordered, s_unordered, po])
    await db.commit()

    result = await get_beile_orders_with_stockins(db, page=1, per_page=50)
    by_id = {r['id']: r for r in result['items']}
    assert by_id[301]['is_ordered'] is True
    assert by_id[302]['is_ordered'] is False

    assert (await confirm_beile_stockin(db, 301, QA_USER))['success'] is True
    with pytest.raises(ConflictError) as exc:
        await confirm_beile_stockin(db, 302, QA_USER)
    assert exc.value.status_code == 409
    assert exc.value.message == BEILE_NOT_ORDERED_DETAIL


# =========================================================================
# D. NULL / 空值边界
# =========================================================================
async def test_qa_complete_purchase_order_none_rate_keeps_stored_value(db):
    """spare_rate=None 不得覆盖已存 spare_rate/spare_quantity（PRD Q1）。"""
    from fastapi_app.services.purchase_order_crud import complete_purchase_order

    po = PurchaseOrder(id=501, order_no='PC-501', status=PurchaseOrderStatus.PENDING,
                       product_name='变形金刚', product_quantity=10000,
                       spare_quantity=500, spare_rate=50)
    item = PurchaseOrderItem(id=1, order_id=501, material_name='布料A', quantity=10)
    db.add_all([_user(), po, item])
    await db.commit()

    await complete_purchase_order(db, 501, 'qa', None)
    await db.commit()
    await db.refresh(po)

    assert po.status == PurchaseOrderStatus.COMPLETED
    assert float(po.spare_rate) == 50, 'spare_rate=None 时被覆盖'
    assert float(po.spare_quantity) == 500, 'spare_quantity=None 时被覆盖'


async def test_qa_complete_purchase_order_with_rate_writes(db):
    """对照组：带 spare_rate=1200（超上限）→ 归一 1000 → spare=ceil(1000*10000/1000)=10000。"""
    from fastapi_app.services.purchase_order_crud import complete_purchase_order

    po = PurchaseOrder(id=502, order_no='PC-502', status=PurchaseOrderStatus.PENDING,
                       product_name='变形金刚', product_quantity=10000)
    item = PurchaseOrderItem(id=2, order_id=502, material_name='布料A', quantity=10)
    db.add_all([_user(), po, item])
    await db.commit()

    await complete_purchase_order(db, 502, 'qa', 1200)
    await db.commit()
    await db.refresh(po)
    assert float(po.spare_rate) == 1000
    assert float(po.spare_quantity) == 10000


async def test_qa_save_factory_summary_edits_empty_edits_with_order_ids(db):
    """Q1 核心路径：edits=[] + order_ids + spare_rate → 必须写入备品。"""
    from fastapi_app.services.purchase_order_crud import save_factory_summary_edits

    po = PurchaseOrder(id=601, order_no='PC-601', status=PurchaseOrderStatus.PENDING,
                       product_name='变形金刚', product_quantity=10000)
    db.add_all([_user(), po])
    await db.commit()

    res = await save_factory_summary_edits(db, [], 'qa', 50, [601])
    await db.commit()
    await db.refresh(po)

    assert res['spare_updated_count'] == 1
    assert float(po.spare_rate) == 50
    assert float(po.spare_quantity) == 500


async def test_qa_save_factory_summary_edits_missing_order_ids_no_raise(db):
    """order_ids 缺失/为空 ⇒ 不抛异常。"""
    from fastapi_app.services.purchase_order_crud import save_factory_summary_edits

    po = PurchaseOrder(id=602, order_no='PC-602', status=PurchaseOrderStatus.PENDING,
                       product_name='变形金刚', product_quantity=10000)
    db.add_all([_user(), po])
    await db.commit()

    res1 = await save_factory_summary_edits(db, [], 'qa', 50, None)
    res2 = await save_factory_summary_edits(db, [], 'qa', 50, [])
    assert res1['spare_updated_count'] == 0
    assert res2['spare_updated_count'] == 0


async def test_qa_save_factory_summary_edits_quantity_none_no_raise(db):
    """edits 含 quantity=None ⇒ 跳过且不抛异常。"""
    from fastapi_app.services.purchase_order_crud import save_factory_summary_edits

    po = PurchaseOrder(id=603, order_no='PC-603', status=PurchaseOrderStatus.PENDING,
                       product_name='变形金刚', product_quantity=10000)
    item = PurchaseOrderItem(id=3, order_id=603, material_name='布料A', quantity=10)
    db.add_all([_user(), po, item])
    await db.commit()

    res = await save_factory_summary_edits(
        db, [{'item_ids': [3], 'quantity': None}], 'qa', None, None,
    )
    assert res['updated_count'] == 0


async def test_qa_stockin_customer_null_normalization(db):
    """NULL 归一：采购单 customer_name=NULL 与备货侧空客户 → 两侧都归一 '' → 已下单且可确认。

    核心断言意图（本用例真正要守的不变量）：
      1) NULL 归一后可匹配 → ``is_ordered is True``（信号成立）；
      2) 归一后的采购单可被确认 → ``confirm_beile_stockin`` 返回 success。

    数量口径（第 3 轮契约更新）：备货行（stockin）只走「精确（带类型）匹配」产出数量；
    「模糊(客户,品名)匹配」是**来源不可靠**路径，仅用于点亮 ``is_ordered`` 信号，
    **绝不产出数量**（见 beile.py `_fetch_completed_po_maps` /
    `_apply_ordered_fields(pos_exact=False)` 契约）。因此本用例中该 PO 的 7777 / spare
    为「模糊来源」，必须为 ``None``，而非旧口径下的 7777。断言已同步至新契约。

    说明（实测约束）：`StockIn.customer` 在模型层是 `nullable=False`（stock_in.py:29），
    故「StockIn.customer=None」在真实 schema 下不可达；可 NULL 的一侧是
    `PurchaseOrder.customer_name`（可空）。本用例覆盖该真实可达的 NULL 归一路径。
    """
    p = Product(id=1, name='变形金刚', barcode='690001', factory='湖北')
    s_empty = StockIn(id=701, stockin_no='SI-701', customer='', product_id=1,
                      quantity=30, stockin_date=datetime(2026, 9, 1))
    po_null = PurchaseOrder(id=801, order_no='PC-801', status=PurchaseOrderStatus.COMPLETED,
                            customer_name=None, product_name='变形金刚',
                            product_quantity=7777, spare_quantity=1, spare_rate=50)
    db.add_all([_user(), p, s_empty, po_null])
    await db.commit()

    result = await get_beile_orders_with_stockins(db, page=1, per_page=50)
    row = next(r for r in result['items'] if r['id'] == 701)
    assert row['is_ordered'] is True, 'customer_name=NULL 与 customer=\'\' 归一后应匹配'
    # 第 3 轮契约：模糊(客户,品名)来源仅点亮 is_ordered，绝不产出数量 → 数量必为 None。
    assert row['purchase_order_qty'] is None, '模糊来源不得产出数量（见 beile.py pos_exact=False 契约）'
    assert row['spare_quantity'] is None, '模糊来源不得产出数量（见 beile.py pos_exact=False 契约）'

    assert (await confirm_beile_stockin(db, 701, QA_USER))['success'] is True


def test_qa_stockin_customer_is_not_null_in_schema():
    """记录事实：StockIn.customer 不可为 NULL ⇒ 备货侧 NULL 场景不可达（口径归一只需覆盖采购单侧）。"""
    assert StockIn.__table__.c.customer.nullable is False
    assert PurchaseOrder.__table__.c.customer_name.nullable is True


# =========================================================================
# E. 缓存失效机制
# =========================================================================
def test_qa_fnmatch_proves_old_pattern_insufficient():
    """反证：原失效模式 'orders:p*' 清不到 beile 缓存，故本次追加 'orders:beile:*' 必要。"""
    import fnmatch
    key = 'orders:beile:list:p1:pp18:cf:cs:pk'
    assert fnmatch.fnmatch(key, 'orders:beile:*') is True
    assert fnmatch.fnmatch(key, 'orders:p*') is False
    # 计数键同样位于 beile 前缀下
    assert fnmatch.fnmatch('orders:beile:unconfirmed_count:f湖北', 'orders:beile:*') is True


async def test_qa_invalidate_orders_cache_covers_beile(monkeypatch):
    """_invalidate_orders_cache 必须同时清 'orders:p*' 与 'orders:beile:*'。"""
    from unittest.mock import AsyncMock
    from fastapi_app.api.v1.endpoints.purchase_center import order_routes

    mock = AsyncMock(return_value=0)
    monkeypatch.setattr(order_routes, 'invalidate_cache', mock)

    await order_routes._invalidate_orders_cache()

    patterns = [c.args[0] for c in mock.await_args_list]
    assert 'orders:p*' in patterns
    assert 'orders:beile:*' in patterns
    assert mock.await_count == 2


async def test_qa_local_ttl_zero_disables_l1(db):
    """local_ttl=0 真正禁用 L1：同键两次调用底层函数被调用两次。

    对照组（local_ttl=30）底层只被调用一次，证明该断言不会假绿。
    """
    from fastapi_app.core.cache import cache_result, invalidate_local_cache

    counter = {'zero': 0, 'normal': 0}

    @cache_result(key_prefix='qa:ttl_zero', ttl=60, local_ttl=0)
    async def _zero():
        counter['zero'] += 1
        return counter['zero']

    @cache_result(key_prefix='qa:ttl_normal', ttl=60, local_ttl=30)
    async def _normal():
        counter['normal'] += 1
        return counter['normal']

    invalidate_local_cache('*')
    await _zero()
    await _zero()
    invalidate_local_cache('*')
    await _normal()
    await _normal()

    assert counter['zero'] == 2, 'local_ttl=0 时 L1 仍在生效（禁用失败）'
    assert counter['normal'] == 1, '对照组异常：L1 未生效，说明测试方法本身失效'


async def test_qa_beile_list_l1_disabled_end_to_end(db, monkeypatch):
    """列表函数端到端证明 local_ttl=0：同键两次调用 → 底层映射函数被调用两次。"""
    from fastapi_app.services.order import beile as beile_module
    from fastapi_app.core.cache import invalidate_local_cache

    p = Product(id=1, name='变形金刚', barcode='690001', factory='湖北')
    o = _order(11, 'PO-11', '客户A', datetime(2026, 9, 1), p, 5)
    db.add_all([_user(), p, o])
    await db.commit()

    invalidate_local_cache('*')
    calls = {'n': 0}
    original = beile_module._fetch_completed_po_maps

    async def _spy(session):
        calls['n'] += 1
        return await original(session)

    monkeypatch.setattr(beile_module, '_fetch_completed_po_maps', _spy)

    await get_beile_orders_with_stockins(db, page=1, per_page=77)
    await get_beile_orders_with_stockins(db, page=1, per_page=77)
    assert calls['n'] == 2, 'beile 列表 L1 未禁用'


async def test_qa_count_function_l1_disabled(db, monkeypatch):
    """未确认计数函数 local_ttl=0：两次调用各自回源（execute 次数翻倍）。"""
    from fastapi_app.core.cache import invalidate_local_cache

    p = Product(id=1, name='变形金刚', barcode='690001', factory='湖北')
    o = _order(11, 'PO-11', '客户A', datetime(2026, 9, 1), p, 5)
    db.add_all([_user(), p, o])
    await db.commit()

    orig_execute = db.execute
    calls = {'n': 0}

    async def _spy(*args, **kwargs):
        calls['n'] += 1
        return await orig_execute(*args, **kwargs)

    monkeypatch.setattr(db, 'execute', _spy)

    invalidate_local_cache('*')
    calls['n'] = 0
    await get_beile_unconfirmed_count(db, factory='湖北')
    first = calls['n']
    await get_beile_unconfirmed_count(db, factory='湖北')
    second = calls['n']
    assert first > 0
    assert second == first * 2, f'unconfirmed_count L1 未禁用（{first} -> {second}）'
