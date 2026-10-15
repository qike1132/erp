"""湖北订单+备货合并查询与确认（services/order/beile.py）服务层回归测试。

使用 sqlite+aiosqlite 内存库 + 真实模型，覆盖：
- UNION 合并列表的字段结构与 record_type 区分（product_image 已下线）
- confirm_status / product_kw 筛选（订单按 SKU、备货按产品）
- 同秒记录的稳定排序（record_type, source_id 次级排序键）
- 页码越界回退（LIMIT 1 窗口 count 探测总数）
- 确认流程：幂等、非湖北 404 隔离、未读通知批量标记已读
- 数量/备品同步（completed 采购单 MAX 口径）：已下单注入、未下单兜底、pending 不算
- 确认门控：未确认且未下单抛 ConflictError（409），confirmed_at 保持 NULL
- 确认幂等（CR-1）：已确认（即使未下单）再次确认 → 200 + already_confirmed=True（幂等早退在门控之前）
- 缓存禁用 L1（local_ttl=0）：失效后必然回源重算，无 L1 短路
"""
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from fastapi_app.core.cache import invalidate_cache
from fastapi_app.core.exceptions import ConflictError, NotFoundError
from fastapi_app.services.notification_service import BEILE_UNCONFIRMED_TYPE
from fastapi_app.services.order.beile import (
    BEILE_NOT_ORDERED_DETAIL,
    confirm_beile_order,
    confirm_beile_stockin,
    get_beile_orders_with_stockins,
)
from fastapi_app.shared_models import (
    Base,
    Notification,
    Order,
    OrderItem,
    Product,
    PurchaseOrder,
    PurchaseOrderStatus,
    StockIn,
    User,
)


@pytest_asyncio.fixture
async def db():
    """真实模型的 sqlite 内存库会话（每个测试独立实例）。

    仅建本测试涉及的表：全量 metadata 含 PG 专用类型（JSONB 等），sqlite 无法编译。
    必须包含 PurchaseOrder（门控与数量同步依赖 completed 采购单）。

    每个用例开始前失效 beile L2 缓存：`get_beile_unconfirmed_count` /
    `get_beile_orders_with_stockins` 带 60s TTL 且 key 不含数据指纹，
    跨用例存活会让「总数/列表」读到上个用例的串号结果（假红）。
    """
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    tables = [
        User.__table__, Product.__table__, Order.__table__,
        OrderItem.__table__, StockIn.__table__, Notification.__table__,
        PurchaseOrder.__table__,
    ]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    maker = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    await invalidate_cache('orders:beile:*')
    async with maker() as session:
        yield session
    await engine.dispose()


async def _seed(db: AsyncSession) -> User:
    """构造湖北/东莞混合的订单+备货+通知+采购单数据。

    期望的 beile-list（无筛选、按日期倒序）：
        o2(9/2 10:00 订单) → s1(9/2 10:00 备货，与 o2 同秒，tiebreaker 订单在前)
        → o1(9/1) → o4(8/30，已确认) → s2(7/1，已确认)
    o3/s3 属东莞工厂，不出现。

    采购单（completed 映射）：
        CPO-001/002 completed source_order_ids=[11] → o1 已下单（两张同单，验证 MAX 去重）
        CPO-003 pending    source_order_ids=[14] → o4 仅 pending，视为未下单
        CPO-004 completed (客户C,变形金刚)         → s1 备货近似匹配已下单
    """
    user = User(id=1, username='hubei_op', password='x', factory='湖北')
    p1 = Product(id=1, name='变形金刚', barcode='690001', factory='湖北')
    p2 = Product(id=2, name='蛋黄派', barcode='690002', factory='湖北')
    p3 = Product(id=3, name='遥控车', barcode='690003', factory='东莞')

    def order(oid: int, no: str, customer: str, date: datetime, product: Product, qty: int, **kw) -> Order:
        return Order(
            id=oid, order_no=no, customer=customer, order_date=date,
            product_id=product.id, quantity=qty,
            items=[OrderItem(product_id=product.id, product_name=product.name,
                             product_barcode=product.barcode, quantity=qty)],
            **kw,
        )

    o1 = order(11, 'PO-011', '客户A', datetime(2026, 9, 1, 10, 0, 0), p1, 10)
    o2 = order(12, 'PO-012', '客户B', datetime(2026, 9, 2, 10, 0, 0), p2, 20)
    o3 = order(13, 'PO-013', '东莞客户', datetime(2026, 9, 3, 10, 0, 0), p3, 5)
    o4 = order(14, 'PO-014', '已确认客户', datetime(2026, 8, 30, 10, 0, 0), p1, 7,
               confirmed_at=datetime(2026, 9, 4, 9, 0, 0), confirmed_by_id=1)

    s1 = StockIn(id=21, stockin_no='SI-021', customer='客户C', product_id=1,
                 quantity=30, stockin_date=datetime(2026, 9, 2, 10, 0, 0))
    s2 = StockIn(id=22, stockin_no='SI-022', customer='客户D', product_id=2,
                 quantity=40, stockin_date=datetime(2026, 7, 1, 10, 0, 0),
                 confirmed_at=datetime(2026, 7, 2, 9, 0, 0))
    s3 = StockIn(id=23, stockin_no='SI-023', customer='东莞备货', product_id=3,
                 quantity=50, stockin_date=datetime(2026, 9, 5, 10, 0, 0))

    po_1 = PurchaseOrder(id=101, order_no='CPO-001', status=PurchaseOrderStatus.COMPLETED,
                         source_order_ids='[11]', supplier_name='供应商甲', customer_name='客户A', product_name='变形金刚',
                         product_quantity=10000, spare_quantity=500, spare_rate=50)
    po_2 = PurchaseOrder(id=102, order_no='CPO-002', status=PurchaseOrderStatus.COMPLETED,
                         source_order_ids='[11]', supplier_name='供应商乙', customer_name='客户A', product_name='变形金刚',
                         product_quantity=10000, spare_quantity=500, spare_rate=50)
    po_pending = PurchaseOrder(id=103, order_no='CPO-003', status=PurchaseOrderStatus.PENDING,
                               source_order_ids='[14]', supplier_name='供应商丙', customer_name='已确认客户', product_name='变形金刚',
                               product_quantity=7)
    po_stockin = PurchaseOrder(id=104, order_no='CPO-004', status=PurchaseOrderStatus.COMPLETED,
                               supplier_name='供应商丁', customer_name='客户C', product_name='变形金刚',
                               product_quantity=8888, spare_quantity=444, spare_rate=50)

    notification = Notification(user_id=1, type=BEILE_UNCONFIRMED_TYPE, title='待确认提醒',
                                content='{}', related_order_id=11, is_read=False)

    db.add_all([user, p1, p2, p3, o1, o2, o3, o4, s1, s2, s3,
                po_1, po_2, po_pending, po_stockin, notification])
    await db.commit()
    return user


async def _seed_mixed_factory(db: AsyncSession) -> None:
    """混工厂订单（复现生产 BUG PO-20261015-2584）：3 SKU 含东莞工厂产品。

    订单因任一湖北 SKU 入选湖北列表（SQL any()），行构建必须把 items 收窄为
    湖北 SKU —— 否则东莞 SKU 会泄漏进湖北列表的页面/详情/导出/打印（AC-12 同源）。
    """
    user = User(id=1, username='hubei_op', password='x', factory='湖北')
    p_hb1 = Product(id=1, name='湖北001', barcode='690011', factory='湖北')
    p_dg = Product(id=2, name='蛋仔派对盲盒', barcode='690012', factory='东莞')
    p_hb2 = Product(id=3, name='湖北004', barcode='690013', factory='湖北')
    o = Order(
        id=50, order_no='PO-20261015-2584', customer='混单客户',
        order_date=datetime(2026, 10, 15, 10, 0, 0), product_id=1, quantity=3,
        items=[
            OrderItem(product_id=1, product_name='湖北001', product_barcode='690011', quantity=1),
            OrderItem(product_id=2, product_name='蛋仔派对盲盒', product_barcode='690012', quantity=1),
            OrderItem(product_id=3, product_name='湖北004', product_barcode='690013', quantity=1),
        ],
    )
    db.add_all([user, p_hb1, p_dg, p_hb2, o])
    await db.commit()


async def test_beile_list_mixed_factory_order_narrows_items_to_factory(db):
    """生产 BUG 回归（2026-10-15）：混工厂订单的 items 必须收窄为本工厂 SKU。

    PO-20261015-2584 含东莞 SKU「蛋仔派对盲盒」；SQL 按「任一湖北 SKU 命中」选整单后，
    行构建若不收窄 items，东莞 SKU 就出现在湖北列表（生产实证 item id=67396 泄漏）。
    """
    await _seed_mixed_factory(db)
    result = await get_beile_orders_with_stockins(db, page=1, per_page=50, customer='混单客户')
    assert [(r['record_type'], r['id']) for r in result['items']] == [('order', 50)]
    row = result['items'][0]
    # items 只含湖北 SKU；东莞 SKU 绝不出现（页面/详情/导出/打印同源，AC-12）
    assert [it['product_name'] for it in row['items']] == ['湖北001', '湖北004']
    assert all(it['product_name'] != '蛋仔派对盲盒' for it in row['items'])
    # 顶部产品名回落到首个本厂 SKU（不再是无工厂归属的首行）
    assert row['product_name'] == '湖北001'


async def test_beile_list_keyword_hit_on_foreign_factory_sku_does_not_leak(db):
    """搜索态同源泄漏回归：关键字只命中他厂 SKU 时，混工厂订单不得出现在湖北列表。"""
    await _seed_mixed_factory(db)
    # 「蛋仔」只命中东莞 SKU → 湖北列表不得出现该订单（旧实现：整单带着东莞行泄漏）
    leaked = await get_beile_orders_with_stockins(
        db, page=1, per_page=50, customer='混单客户', product_kw='蛋仔')
    assert leaked['items'] == []
    # 命中湖北 SKU：订单出现，items 只含命中的湖北 SKU（数量口径同步只统计命中集合）
    hit = await get_beile_orders_with_stockins(
        db, page=1, per_page=50, customer='混单客户', product_kw='湖北')
    assert [(r['record_type'], r['id']) for r in hit['items']] == [('order', 50)]
    assert [it['product_name'] for it in hit['items'][0]['items']] == ['湖北001', '湖北004']


async def test_beile_list_confirm_status_filter(db):
    await _seed(db)
    unconfirmed = await get_beile_orders_with_stockins(db, page=1, per_page=50, confirm_status='unconfirmed')
    assert [(r['record_type'], r['id'], r['confirmed']) for r in unconfirmed['items']] == [
        ('order', 12, False), ('stockin', 21, False), ('order', 11, False),
    ]

    confirmed = await get_beile_orders_with_stockins(db, page=1, per_page=50, confirm_status='confirmed')
    assert [(r['record_type'], r['id'], r['confirmed']) for r in confirmed['items']] == [
        ('order', 14, True), ('stockin', 22, True),
    ]


async def test_beile_list_product_keyword_filter(db):
    await _seed(db)
    # 条码 690002：订单侧命中 SKU 明细（o2），备货侧命中产品（s2），互不串号
    result = await get_beile_orders_with_stockins(db, page=1, per_page=50, product_kw='690002')
    assert [(r['record_type'], r['id']) for r in result['items']] == [('order', 12), ('stockin', 22)]

    # 产品名关键字命中备货产品
    result = await get_beile_orders_with_stockins(db, page=1, per_page=50, product_kw='变形金刚')
    assert [(r['record_type'], r['id']) for r in result['items']] == [
        ('stockin', 21), ('order', 11), ('order', 14),
    ]


async def test_beile_list_page_beyond_end_falls_back_to_probe_total(db):
    await _seed(db)
    result = await get_beile_orders_with_stockins(db, page=9, per_page=18)
    assert result['items'] == []
    assert result['total'] == 5  # 页码越界仍返回真实总数，前端分页不塌陷

    empty = await get_beile_orders_with_stockins(db, page=1, per_page=18, customer='不存在客户')
    assert empty['items'] == []
    assert empty['total'] == 0


async def test_beile_list_ordered_fields_use_max_not_sum(db):
    """AC-1/AC-2/AC-8：已下单行按 completed 采购单 MAX 口径注入，重复采购单不叠加。"""
    await _seed(db)
    result = await get_beile_orders_with_stockins(db, page=1, per_page=50)
    by_key = {(r['record_type'], r['id']): r for r in result['items']}

    # 两张 completed 同客户订单（各 qty=10000/spare=500）→ MAX 仍为 10000/500，不叠加
    o11 = by_key[('order', 11)]
    assert o11['is_ordered'] is True
    assert o11['purchase_order_qty'] == 10000
    assert o11['spare_quantity'] == 500
    assert o11['spare_rate'] == 50

    # 未下单订单：保留客户订单原数量，备品 0 / 率 None
    o12 = by_key[('order', 12)]
    assert o12['is_ordered'] is False
    assert o12['purchase_order_qty'] == 20
    assert o12['spare_quantity'] == 0
    assert o12['spare_rate'] is None

    # 仅存在 pending 采购单 → 不算已下单（PRD Q4）
    o14 = by_key[('order', 14)]
    assert o14['is_ordered'] is False
    assert o14['purchase_order_qty'] == 7
    assert o14['spare_quantity'] == 0
    assert o14['spare_rate'] is None

    # 备货行按 (customer, product_name) 模糊匹配 completed 采购单（PRD Q2）：
    # D-R2-1 修正后，模糊匹配**只决定 is_ordered，绝不产出数量**（该备货无精确逐 SKU 行 →
    # purchase_order_qty / spare_quantity 一律 None），避免把模糊命中的
    # MAX(product_quantity)=8888 当成该备货自己的数量（编造数字）；spare_rate 仅作展示提示。
    s21 = by_key[('stockin', 21)]
    assert s21['is_ordered'] is True
    assert s21['purchase_order_qty'] is None
    assert s21['spare_quantity'] is None
    assert s21['spare_rate'] == 50

    # 无匹配 completed 采购单的备货 → 未下单，保留 stockin.quantity
    s22 = by_key[('stockin', 22)]
    assert s22['is_ordered'] is False
    assert s22['purchase_order_qty'] == 40
    assert s22['spare_quantity'] == 0
    assert s22['spare_rate'] is None


async def test_ordered_spare_rate_zero_survives(db):
    """边界：spare_rate=0 是合法「已记录」值，不得被当成缺失（None）。"""
    await _seed(db)
    db.add(PurchaseOrder(id=105, order_no='CPO-005', status=PurchaseOrderStatus.COMPLETED,
                         source_order_ids='[12]', customer_name='客户B', product_name='蛋黄派',
                         product_quantity=2000, spare_quantity=0, spare_rate=0))
    await db.commit()

    result = await get_beile_orders_with_stockins(db, page=1, per_page=51)
    o12 = next(r for r in result['items'] if r['record_type'] == 'order' and r['id'] == 12)
    assert o12['is_ordered'] is True
    assert o12['purchase_order_qty'] == 2000
    assert o12['spare_quantity'] == 0
    assert o12['spare_rate'] == 0


async def test_beile_list_response_has_no_unordered_count(db):
    """契约回归：`unordered_count` 已随顶部横幅下线，响应中不得再出现该键。

    同时确认 `is_ordered` 事实字段仍严格判定（未下单即为 False，与确认状态无关），
    证明下线计数未波及行级口径。
    """
    await _seed(db)
    result = await get_beile_orders_with_stockins(db, page=1, per_page=50, confirm_status='unconfirmed')

    assert 'unordered_count' not in result, 'unordered_count 已下线，响应不应再携带该键'
    assert result['unconfirmed_count'] == 3

    # 行级事实字段不受影响：o4(14) 未下单但已确认 → is_ordered 仍为 False
    all_rows = await get_beile_orders_with_stockins(db, page=1, per_page=50)
    by_id = {r['id']: r for r in all_rows['items']}
    assert by_id[14]['is_ordered'] is False


async def test_beile_list_cache_has_no_l1_short_circuit(db, monkeypatch):
    """R1 处置回归：local_ttl=0 ⇒ L1 永不命中，失效后必然回源重算。

    生产为多 worker（UVICORN_WORKERS=8）且 L1 广播关闭，L1 无法跨 worker 失效；
    必须禁用 L1，使采购侧 `invalidate_cache('orders:beile:*')` 删掉 L2 键后
    所有 worker 立即回源（AC-10 ≤1s）。此处关闭 L2，纯观察 L1：同键两次调用
    必须两次都回源（若 L1 生效则第二次被短路，底层函数只会被调用 1 次）。
    """
    await _seed(db)
    from fastapi_app.core import cache as cache_module
    from fastapi_app.services.order import beile as beile_module

    monkeypatch.setattr(cache_module, '_get_redis_cache', lambda: None)
    cache_module.invalidate_local_cache('orders:beile:*')

    calls = {'count': 0}
    original = beile_module._fetch_completed_po_maps

    async def _spy(session):
        calls['count'] += 1
        return await original(session)

    monkeypatch.setattr(beile_module, '_fetch_completed_po_maps', _spy)

    await get_beile_orders_with_stockins(db, page=1, per_page=52)
    await get_beile_orders_with_stockins(db, page=1, per_page=52)

    assert calls['count'] == 2, 'local_ttl 必须为 0：L1 命中了进程内缓存（多 worker 下会脏读）'


async def test_confirm_beile_order_marks_notification_and_is_idempotent(db):
    user = await _seed(db)
    result = await confirm_beile_order(db, 11, user)
    assert result['success'] is True
    assert result['already_confirmed'] is False

    # 该订单的未读提醒被标记已读
    unread = await db.execute(
        select(Notification).where(
            Notification.related_order_id == 11,
            Notification.type == BEILE_UNCONFIRMED_TYPE,
            Notification.is_read.is_(False),
        )
    )
    assert unread.scalars().all() == []

    # 幂等：重复确认返回 already_confirmed
    again = await confirm_beile_order(db, 11, user)
    assert again['success'] is True
    assert again['already_confirmed'] is True


async def test_confirm_beile_order_rejected_when_not_ordered(db):
    """AC-5：未在采购中心完成下单的订单确认被拒（409），confirmed_at 仍为 NULL。"""
    user = await _seed(db)
    with pytest.raises(ConflictError) as exc:
        await confirm_beile_order(db, 12, user)
    assert exc.value.status_code == 409
    assert exc.value.message == BEILE_NOT_ORDERED_DETAIL

    order = await db.get(Order, 12)
    assert order.confirmed_at is None


def test_fmt_beile_time_converts_utc_to_beijing():
    """BUG 修复回归：beile-list 的时间输出必须 UTC→北京时间（+8）。

    旧实现对 order_date / stockin_date（timestamptz，DB 存 UTC）与
    confirmed_at（naive UTC）裸 strftime，把 UTC 时刻当地面时间输出 →
    页面「下单时间」比实际早 8 小时（实证：订单号 PO-20260918-0001
    显示 2026-09-17 22:20，与订单号日期矛盾）。
    """
    from datetime import UTC

    from fastapi_app.services.order.beile import _fmt_beile_time

    # timestamptz 列：DB 读回 aware UTC → 转 +8
    assert _fmt_beile_time(datetime(2026, 9, 18, 5, 38, tzinfo=UTC)) == '2026-09-18 13:38'
    # naive 列（confirmed_at 写入口径 = now(UTC).replace(tzinfo=None)）→ 按 UTC 解释转 +8
    assert _fmt_beile_time(datetime(2026, 9, 18, 6, 31)) == '2026-09-18 14:31'
    # 跨日边界：UTC 22:20 → 次日 06:20（「下单时间与订单号日期对不上」的关键场景）
    assert _fmt_beile_time(datetime(2026, 9, 17, 22, 20, tzinfo=UTC)) == '2026-09-18 06:20'
    # NULL → ''（前端展示 '-'）
    assert _fmt_beile_time(None) == ''


def test_apply_ordered_fields_search_scope_qty_only_matched():
    """SKU 级搜索的数量口径：search_qty_items 非 None 时数量只统计命中集合。

    BUG 修复回归：旧实现搜索命中后数量仍为全单口径（rollup 全部 SKU /
    MAX(product_quantity) / record['quantity']），用户视角即「搜索变形金刚
    显示整个订单的总数量」。
    """
    from fastapi_app.services.order.beile import _apply_ordered_fields

    # 未下单：命中 items 求和（不是全单 record['quantity']=100）
    rec = {'quantity': 100}
    _apply_ordered_fields(rec, pos=[], sku_rows=[], search_qty_items=[{'quantity': 60}])
    assert rec['purchase_order_qty'] == 60
    assert rec['spare_quantity'] == 0
    assert rec['is_ordered'] is False

    class _Po:
        id = 101
        spare_rate = 5

    class _SkuRow:
        po_id = 101
        product_name = '变形金刚'
        order_qty = 66
        spare_qty = 6
        spare_rate = 5

    # 已下单 + 命中集合的逐 SKU 快照（caller 已预过滤）→ rollup 命中集合
    rec2: dict = {}
    _apply_ordered_fields(rec2, pos=[_Po()], sku_rows=[_SkuRow()], search_qty_items=[{'quantity': 60}])
    assert rec2['is_ordered'] is True
    assert rec2['purchase_order_qty'] == 66
    assert rec2['spare_quantity'] == 6

    # 已下单 + 无逐 SKU 快照 → None（不把全单 MAX(product_quantity) 编造成命中集合数量）
    rec3: dict = {}
    _apply_ordered_fields(rec3, pos=[_Po()], sku_rows=[], search_qty_items=[{'quantity': 60}])
    assert rec3['purchase_order_qty'] is None
    assert rec3['spare_quantity'] is None


async def test_beile_list_search_narrows_items_and_qty_to_matched_skus(db, monkeypatch):
    """SKU 级搜索（端到端）：命中订单的 items 只保留命中 SKU，数量只统计命中集合。

    多 SKU 订单 o5（变形金刚 60 + 蛋黄派 40）搜索「变形金刚」：
    - items 收窄为 [变形金刚]；
    - 未下单数量 = 60（命中求和），绝不再是全单 100；
    - 对照无关键字：items 全量、数量为全单口径。
    """
    # /beile-list 带 60s L2 缓存，先前用例的同 key 结果会短路本用例 → 关闭缓存
    from fastapi_app.core import cache as cache_module

    monkeypatch.setattr(cache_module, '_get_redis_cache', lambda: None)
    cache_module.invalidate_local_cache('orders:beile:*')

    await _seed(db)
    o5 = Order(
        id=15, order_no='PO-015', customer='多SKU客户', order_date=datetime(2026, 9, 5, 10, 0, 0),
        product_id=1, quantity=100,
        items=[
            OrderItem(product_id=1, product_name='变形金刚', product_barcode='690001', quantity=60),
            OrderItem(product_id=2, product_name='蛋黄派', product_barcode='690002', quantity=40),
        ],
    )
    db.add(o5)
    await db.commit()

    result = await get_beile_orders_with_stockins(db, page=1, per_page=50, product_kw='变形金刚')
    o5row = next(r for r in result['items'] if r['record_type'] == 'order' and r['id'] == 15)
    assert [it['product_name'] for it in o5row['items']] == ['变形金刚']
    assert o5row['is_ordered'] is False
    assert o5row['purchase_order_qty'] == 60

    # 对照：无关键字时 items 全量、既有口径不变（零回归）
    plain = await get_beile_orders_with_stockins(db, page=1, per_page=50)
    row15 = next(r for r in plain['items'] if r['record_type'] == 'order' and r['id'] == 15)
    assert [it['product_name'] for it in row15['items']] == ['变形金刚', '蛋黄派']
    # 既有兼容字段语义（铁律 D★）：未下单 purchase_order_qty = record['quantity'] = 首个 SKU 原数量
    assert row15['purchase_order_qty'] == 60
    # 订单级合计口径（items 求和）= 全单 100
    assert sum(it['quantity'] or 0 for it in row15['items']) == 100


async def test_confirm_already_confirmed_unordered_returns_idempotent_200(db):
    """CR-1：幂等早退必须在门控之前。

    对「**已确认** 且 **未下单**」的记录再次确认，必须返回幂等成功
    （`success=True` / `already_confirmed=True`，对应 HTTP 200），
    而不是被「未下单」门控拦成 409——否则改动前「重复确认幂等 200」的行为会回退。
    订单（o4=14，仅有 pending 采购单）与备货（s2=22，无匹配 completed 采购单）各一例。
    """
    user = await _seed(db)

    res_order = await confirm_beile_order(db, 14, user)
    assert res_order['success'] is True
    assert res_order['already_confirmed'] is True

    res_stockin = await confirm_beile_stockin(db, 22, user)
    assert res_stockin['success'] is True
    assert res_stockin['already_confirmed'] is True


async def test_confirm_beile_order_rejects_non_hubei_and_missing(db):
    user = await _seed(db)
    with pytest.raises(NotFoundError):
        await confirm_beile_order(db, 13, user)  # 东莞订单
    with pytest.raises(NotFoundError):
        await confirm_beile_order(db, 999, user)  # 不存在


async def test_confirm_beile_stockin_idempotent_and_isolated(db):
    user = await _seed(db)
    result = await confirm_beile_stockin(db, 21, user)
    assert result['success'] is True
    assert result['already_confirmed'] is False

    again = await confirm_beile_stockin(db, 21, user)
    assert again['already_confirmed'] is True

    with pytest.raises(NotFoundError):
        await confirm_beile_stockin(db, 23, user)  # 东莞备货
    with pytest.raises(NotFoundError):
        await confirm_beile_stockin(db, 999, user)  # 不存在


async def test_confirm_beile_stockin_rejected_when_not_ordered(db):
    """AC-9：无匹配 completed 采购单的备货确认被拒（409），confirmed_at 仍为 NULL。"""
    user = await _seed(db)
    # seed 中 s2 已确认，这里将其重置为未确认以触发门控路径
    stockin = await db.get(StockIn, 22)
    stockin.confirmed_at = None
    await db.commit()

    with pytest.raises(ConflictError) as exc:
        await confirm_beile_stockin(db, 22, user)
    assert exc.value.status_code == 409
    assert exc.value.message == BEILE_NOT_ORDERED_DETAIL

    await db.refresh(stockin)
    assert stockin.confirmed_at is None
