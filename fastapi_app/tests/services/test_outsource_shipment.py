"""外发发货单（一键发货工作流）服务测试。

覆盖：
- create_shipment：一键发货生成发货单 + 发货工序 + 明细 + 通知
- receive_shipment：确认收货 shipped → received，幂等
- list_shipments：状态筛选 + 计数

使用 sqlite 内存库 + 真实模型（不 mock 生产者），编号生成 monkeypatch 为固定值，
避开 numbering_counter 与 PG advisory lock 的 sqlite 兼容问题。
"""
from datetime import datetime

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from fastapi_app.services.outsource import _shipments as shipments_mod
from fastapi_app.services.outsource._order_processes import receive_order_process
from fastapi_app.services.outsource._shipments import (
    create_merged_shipment,
    create_shipment,
    get_shipment,
    list_shipments,
    receive_shipment,
)
from fastapi_app.shared_models import (
    SHIPMENT_STATUS_RECEIVED,
    Base,
    Notification,
    Order,
    OrderItem,
    OrderOutsourceProcess,
    OrderOutsourceProcessFlow,
    OutsourceShipment,
    OutsourceShipmentItem,
    Permission,
    Product,
    User,
    user_permission,
)


@pytest_asyncio.fixture
async def db(monkeypatch):
    """真实模型 sqlite 内存库（含发货单两张表 + 用户/权限关联表）。"""
    counter = {'n': 0}

    async def _fake_number(_db):
        counter['n'] += 1
        return f'FH-20260919-{counter["n"]:04d}'

    monkeypatch.setattr(shipments_mod, 'generate_shipment_number', _fake_number)

    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    tables = [
        User.__table__, Permission.__table__, user_permission,
        Product.__table__, Order.__table__, OrderItem.__table__,
        OrderOutsourceProcess.__table__, OrderOutsourceProcessFlow.__table__,
        OutsourceShipment.__table__, OutsourceShipmentItem.__table__,
        Notification.__table__,
    ]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    maker = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _seed(db):
    """种入最小业务数据：湖北产品 + 订单 + 明细 + 待发货工序 + 贝乐收货账号。"""
    product = Product(id=1, name='电绣品', barcode='B1', factory='湖北')
    order = Order(id=1, order_no='PO-20260919-0001', customer='贝乐客户', order_date=datetime(2026, 9, 19, 10, 0),
                  product_id=1, quantity=10)
    item = OrderItem(id=1, order_id=1, product_id=1, product_name='电绣品', product_barcode='B1', quantity=10)
    process = OrderOutsourceProcess(id=1, order_id=1, order_item_id=1, product_id=1,
                                    product_name='电绣品', process_type='电绣', sort_order=0, status='pending')
    user = User(id=1, username='beile', password='x')
    perm = Permission(id=1, name='外发收货', code='outsource_receive')
    user.permissions.append(perm)
    db.add_all([product, order, item, process, user, perm])
    await db.commit()
    return order, process


async def test_create_shipment_ships_and_notifies(db):
    """一键发货：生成发货单 + 发货工序 + 明细 + 向贝乐收货账号派发通知。"""
    order, process = await _seed(db)

    result = await create_shipment(db, order.id, [(process.id, 5)], username='shipper')

    assert result['shipment_no'] == 'FH-20260919-0001'
    assert result['status'] == 'shipped'
    assert result['customer'] == '贝乐客户'
    assert result['total_shipped'] == 5
    assert result['item_count'] == 1
    assert result['items'][0]['process_type'] == '电绣'
    assert result['items'][0]['shipped_quantity'] == 5

    # 工序实例被发货（pending → shipped，数量累计）
    p = await db.get(OrderOutsourceProcess, process.id)
    assert p.status == 'shipped'
    assert p.shipped_quantity == 5

    # 发货单落库
    rows = (await db.execute(select(OutsourceShipment))).scalars().all()
    assert len(rows) == 1
    assert rows[0].shipment_no == 'FH-20260919-0001'

    # 向 outsource_receive 权限账号派发了「待收货」通知
    notif = (await db.execute(select(Notification))).scalars().all()
    assert len(notif) == 1
    assert notif[0].type == 'outsource_shipment_shipped'


async def test_receive_shipment_idempotent(db):
    """确认收货：shipped → received，重复确认幂等返回 already_received。"""
    order, process = await _seed(db)
    shipment = await create_shipment(db, order.id, [(process.id, 5)], username='shipper')

    r1 = await receive_shipment(db, shipment['id'], username='beile')
    assert r1['already_received'] is False

    p = await db.get(OrderOutsourceProcess, process.id)
    assert p.status == 'received'
    assert p.received_quantity == 5

    ship = await db.get(OutsourceShipment, shipment['id'])
    assert ship.status == 'received'
    assert ship.received_by == 'beile'

    # 幂等：重复确认直接返回成功，不重复回写
    r2 = await receive_shipment(db, shipment['id'], username='beile')
    assert r2['already_received'] is True
    assert r2['success'] is True


async def test_receive_shipment_split_same_process(db):
    """回归（第八轮审计）：同一工序**分批发货**时，逐张发货单收货应各收本批数量，
    不应把整道工序一次收满 —— 否则第二张发货单收货会报「该工序已收货」。"""
    product = Product(id=1, name='电绣品', barcode='B1', factory='湖北')
    order = Order(id=1, order_no='PO-20260919-0002', customer='贝乐客户',
                  order_date=datetime(2026, 9, 19, 10, 0), product_id=1, quantity=100)
    item = OrderItem(id=1, order_id=1, product_id=1, product_name='电绣品', product_barcode='B1', quantity=100)
    process = OrderOutsourceProcess(id=1, order_id=1, order_item_id=1, product_id=1,
                                    product_name='电绣品', process_type='电绣', sort_order=0, status='pending')
    db.add_all([product, order, item, process])
    await db.commit()

    s1 = await create_shipment(db, order.id, [(process.id, 60)], username='shipper')
    s2 = await create_shipment(db, order.id, [(process.id, 40)], username='shipper')

    await receive_shipment(db, s1['id'], username='beile')
    p = await db.get(OrderOutsourceProcess, process.id)
    assert p.received_quantity == 60, f'收第一批发货单后应只收 60，实际 {p.received_quantity}'

    await receive_shipment(db, s2['id'], username='beile')
    p = await db.get(OrderOutsourceProcess, process.id)
    assert p.received_quantity == 100


async def test_receive_shipment_succeeds_after_process_already_fully_received(db):
    """回归（2026-11-16 上线前审计 H-1）：工序已被「一键收货」收满后，确认发货单必须成功且不重复计数。

    事故形态：贝乐先在工序面板点「一键收货」（数量缺省 = 整道剩余）→ 工序 received == shipped；
    随后到发货单页点「确认收货」→ 旧实现里 receive_order_process 命中 _is_fully_received 抛
    「该工序已收货，无需重复操作」→ 整事务回滚 → 发货单永久停在 shipped，且没有任何闭环出口。
    """
    order, process = await _seed(db)
    s = await create_shipment(db, order.id, [(process.id, 5)], username='shipper')

    # 先经工序面板把这道工序收满（数量缺省 = 整道剩余）
    await receive_order_process(db, process.id, username='beile')
    p = await db.get(OrderOutsourceProcess, process.id)
    assert (p.received_quantity or 0) == 5, f'前置：工序应已收满 5，实际 {p.received_quantity}'

    # 再确认发货单：必须成功（旧实现此处抛 ValueError）
    result = await receive_shipment(db, s['id'], username='beile')
    assert result['success'] is True
    assert result['already_received'] is False

    ship = await db.get(OutsourceShipment, s['id'])
    assert ship.status == SHIPMENT_STATUS_RECEIVED
    p = await db.get(OrderOutsourceProcess, process.id)
    assert (p.received_quantity or 0) == 5, '发货单确认收货不得把工序收货量重复累加'


async def test_receive_shipment_clamps_to_process_remaining(db):
    """回归（H-1 第二种形态）：工序剩余量小于本单发货量时，确认发货单按剩余量收，不得报错。

    旧实现把 item.shipped_quantity 原样传下去，qty > remaining 直接抛
    「收货数量需在 1-N 之间」→ 同样卡死发货单。
    """
    order, process = await _seed(db)
    s1 = await create_shipment(db, order.id, [(process.id, 3)], username='shipper')
    s2 = await create_shipment(db, order.id, [(process.id, 4)], username='shipper')  # 累计已发 7

    # 工序面板先收 5（剩余从 7 变 2），此时 s2 的 4 已超过剩余
    await receive_order_process(db, process.id, username='beile', received_quantity=5)

    await receive_shipment(db, s2['id'], username='beile')
    p = await db.get(OrderOutsourceProcess, process.id)
    assert (p.received_quantity or 0) == 7, f'应按工序剩余量收到 7，实际 {p.received_quantity}'
    ship2 = await db.get(OutsourceShipment, s2['id'])
    assert ship2.status == SHIPMENT_STATUS_RECEIVED

    # s1 早已被前面那次「一键收货」覆盖，确认它同样能闭环（不重复计数）
    await receive_shipment(db, s1['id'], username='beile')
    p = await db.get(OrderOutsourceProcess, process.id)
    assert (p.received_quantity or 0) == 7


async def test_list_shipments_filters_and_counts(db):
    """列表：状态筛选 + 待收货/已完成计数。"""
    order, process = await _seed(db)
    s1 = await create_shipment(db, order.id, [(process.id, 3)], username='shipper')

    # 第二道工序 → 第二张发货单，并确认收货
    process2 = OrderOutsourceProcess(id=2, order_id=1, order_item_id=1, product_id=1,
                                     product_name='电绣品', process_type='转印', sort_order=1, status='pending')
    db.add(process2)
    await db.commit()
    s2 = await create_shipment(db, order.id, [(process2.id, 4)], username='shipper')
    await receive_shipment(db, s2['id'], username='beile')

    # 待收货
    shipped = await list_shipments(db, status='shipped', page=1, per_page=50)
    assert shipped['shipped_count'] == 1
    assert shipped['received_count'] == 1
    assert [s['id'] for s in shipped['items']] == [s1['id']]

    # 已完成
    received = await list_shipments(db, status='received', page=1, per_page=50)
    assert [s['id'] for s in received['items']] == [s2['id']]

    # 全部
    all_rows = await list_shipments(db, status=None, page=1, per_page=50)
    assert all_rows['total'] == 2


async def test_create_shipment_multiple_processes_one_call(db):
    """回归：一键发货一次提交多道工序（多 SKU/多工序）——后端单次 create_shipment 应生成多明细。"""
    order, process = await _seed(db)
    process2 = OrderOutsourceProcess(id=2, order_id=1, order_item_id=1, product_id=1,
                                     product_name='电绣品', process_type='转印', sort_order=1, status='pending')
    db.add(process2)
    await db.commit()

    result = await create_shipment(db, order.id, [(process.id, 5), (process2.id, 3)], username='shipper')

    assert result['item_count'] == 2
    assert result['total_shipped'] == 8
    assert sorted(it['process_type'] for it in result['items']) == ['电绣', '转印']
    assert {it['shipped_quantity'] for it in result['items']} == {5, 3}

    # 两道工序各自已发货
    p1 = await db.get(OrderOutsourceProcess, process.id)
    p2 = await db.get(OrderOutsourceProcess, process2.id)
    assert p1.shipped_quantity == 5
    assert p2.shipped_quantity == 3


async def test_list_shipments_response_schema_mapping(db):
    """回归：服务返回 `items` 键，响应模型字段是 `data`，端点须显式映射（否则 500）。

    线上 500 根因：`ShipmentListResponse(**result)` 把 `items` 当字段，而 schema 里
    必填字段是 `data` → ValidationError。此处按修复后的端点映射方式构造，断言 data 正确。
    """
    from fastapi_app.schemas.outsource import ShipmentListResponse

    order, process = await _seed(db)
    await create_shipment(db, order.id, [(process.id, 5)], username='shipper')

    result = await list_shipments(db, status='shipped', page=1, per_page=50)
    resp = ShipmentListResponse(
        data=result['items'],
        total=result['total'],
        page=result['page'],
        per_page=result['per_page'],
        shipped_count=result['shipped_count'],
        received_count=result['received_count'],
    )
    assert resp.total == 1
    assert resp.shipped_count == 1
    assert len(resp.data) == 1
    assert resp.data[0].shipment_no == 'FH-20260919-0001'
    assert resp.data[0].status == 'shipped'
    assert resp.data[0].total_shipped == 5


async def test_get_shipment_items_include_order_qty(db):
    """明细：每行返回该工序的订单数量 order_qty（供前端「订单总数」列展示）。"""
    order, process = await _seed(db)
    # _seed 中订单明细数量为 10，即该工序的订单数量口径
    created = await create_shipment(db, order.id, [(process.id, 5)], username='shipper')
    detail = await get_shipment(db, created['id'])

    assert detail is not None
    assert detail['items'][0]['order_qty'] == 10
    # 分批发货：订单总数可大于本次发货数量
    assert detail['items'][0]['shipped_quantity'] == 5


async def test_get_shipment_order_qty_none_when_process_deleted(db):
    """明细：工序被删除（process_id 置空）时 order_qty 为空，前端显示 '-'。"""
    order, process = await _seed(db)

    created = await create_shipment(db, order.id, [(process.id, 5)], username='shipper')
    # 模拟工序删除后外键置空（ON DELETE SET NULL）
    item = (await db.execute(select(OutsourceShipmentItem))).scalars().one()
    item.process_id = None
    await db.commit()

    detail = await get_shipment(db, created['id'])
    assert detail is not None
    assert detail['items'][0]['order_qty'] is None


async def test_create_merged_shipment_across_orders(db):
    """合并发货：跨订单/跨客户多道工序合并为一张发货单，order_id/customer 置空、通知省略客户名。"""
    import json

    _order, process = await _seed(db)
    # 第二个订单（不同客户）
    order2 = Order(id=2, order_no='PO-20260919-0002', customer='客户B', order_date=datetime(2026, 9, 19, 11, 0),
                   product_id=1, quantity=20)
    item2 = OrderItem(id=2, order_id=2, product_id=1, product_name='电绣品', product_barcode='B1', quantity=20)
    process2 = OrderOutsourceProcess(id=2, order_id=2, order_item_id=2, product_id=1,
                                     product_name='电绣品', process_type='转印', sort_order=1, status='pending')
    db.add_all([order2, item2, process2])
    await db.commit()

    result = await create_merged_shipment(db, [(process.id, 5), (process2.id, 8)], username='shipper')

    assert result['order_id'] is None
    assert result['customer'] is None
    assert result['status'] == 'shipped'
    assert result['item_count'] == 2
    assert result['total_shipped'] == 13
    assert sorted(it['process_type'] for it in result['items']) == ['电绣', '转印']

    # 仅落库一张发货单，order_id/customer 均为 None
    rows = (await db.execute(select(OutsourceShipment))).scalars().all()
    assert len(rows) == 1
    assert rows[0].order_id is None
    assert rows[0].customer is None

    # 两道工序各自已发货
    p1 = await db.get(OrderOutsourceProcess, process.id)
    p2 = await db.get(OrderOutsourceProcess, process2.id)
    assert p1.shipped_quantity == 5
    assert p2.shipped_quantity == 8

    # 通知仅一条，且 content 不含 customer 键
    notif = (await db.execute(select(Notification))).scalars().all()
    assert len(notif) == 1
    assert notif[0].type == 'outsource_shipment_shipped'
    content = json.loads(notif[0].content)
    assert 'customer' not in content
    assert content['shipment_no'] == rows[0].shipment_no



async def test_receive_shipment_item_records_applied_quantity_when_clamped(db):
    """回归（推送前 OCR 复审）：工序剩余量 < 本单发货量时，明细「收货数量」= 实际回写量。

    形态：工序累计已发 40（本发货单即为全部 40），人工入口先在工序面板收了 30（剩余 10），
    再确认本发货单 → 工序侧只回写 10。旧实现明细恒写 shipped_quantity=40 ⇒ 明细虚高 30，
    按发货单做的收货台账与工序台账对不上（工序侧数据是对的，只有明细侧错）。
    """
    product = Product(id=1, name='电绣品', barcode='B1', factory='湖北')
    order = Order(id=1, order_no='PO-20260919-0003', customer='贝乐客户',
                  order_date=datetime(2026, 9, 19, 10, 0), product_id=1, quantity=100)
    order_item = OrderItem(id=1, order_id=1, product_id=1, product_name='电绣品',
                           product_barcode='B1', quantity=100)
    process = OrderOutsourceProcess(id=1, order_id=1, order_item_id=1, product_id=1,
                                    product_name='电绣品', process_type='电绣', sort_order=0, status='pending')
    db.add_all([product, order, order_item, process])
    await db.commit()

    s = await create_shipment(db, order.id, [(process.id, 40)], username='shipper')

    # 人工入口先收 30 → 工序剩余 10（本单发货量 40 大于剩余）
    await receive_order_process(db, process.id, username='beile', received_quantity=30)

    await receive_shipment(db, s['id'], username='beile')

    p = await db.get(OrderOutsourceProcess, process.id)
    assert (p.received_quantity or 0) == 40, f'工序侧应为 30+10=40，实际 {p.received_quantity}'

    detail = await get_shipment(db, s['id'])
    assert detail['items'][0]['shipped_quantity'] == 40
    assert detail['items'][0]['received_quantity'] == 10, (
        f'明细应记本单实际回写量 10（不是发货量 40），实际 {detail["items"][0]["received_quantity"]}'
    )


async def test_receive_shipment_item_zero_when_process_has_no_remaining(db):
    """回归（推送前 OCR 复审）：工序已无剩余（receive_order_process 返回 None）时，
    明细「收货数量」记 0（本次未回写工序），且发货单仍照常转 received。"""
    order, process = await _seed(db)
    s = await create_shipment(db, order.id, [(process.id, 5)], username='shipper')

    # 工序面板「一键收货」先把整道工序收满 → 本单确认收货时剩余为 0
    await receive_order_process(db, process.id, username='beile')
    p = await db.get(OrderOutsourceProcess, process.id)
    assert (p.received_quantity or 0) == 5, f'前置：工序应已收满 5，实际 {p.received_quantity}'

    result = await receive_shipment(db, s['id'], username='beile')
    assert result['success'] is True
    assert result['already_received'] is False

    ship = await db.get(OutsourceShipment, s['id'])
    assert ship.status == SHIPMENT_STATUS_RECEIVED, '发货单仍须闭环为 received'

    p = await db.get(OrderOutsourceProcess, process.id)
    assert (p.received_quantity or 0) == 5, '工序不得被重复累加'

    item = (await db.execute(
        select(OutsourceShipmentItem).where(OutsourceShipmentItem.shipment_id == s['id'])
    )).scalars().one()
    assert item.shipped_quantity == 5
    assert (item.received_quantity or 0) == 0, (
        f'本次未回写工序，明细应记 0（不是发货量 5），实际 {item.received_quantity}'
    )


async def test_receive_shipment_item_without_process_records_shipped_quantity(db):
    """无工序可回写的明细（工序已删除 → process_id 置空）保持原语义：收货数量 = 发货数量。"""
    order, process = await _seed(db)
    s = await create_shipment(db, order.id, [(process.id, 5)], username='shipper')

    # 模拟工序删除后外键置空（ON DELETE SET NULL）
    item = (await db.execute(select(OutsourceShipmentItem))).scalars().one()
    item.process_id = None
    await db.commit()

    await receive_shipment(db, s['id'], username='beile')

    ship = await db.get(OutsourceShipment, s['id'])
    assert ship.status == SHIPMENT_STATUS_RECEIVED

    detail = await get_shipment(db, s['id'])
    assert detail['items'][0]['process_id'] is None
    assert detail['items'][0]['shipped_quantity'] == 5
    assert detail['items'][0]['received_quantity'] == 5, (
        '无工序可回写时明细按本单发货量记账（原语义）'
    )
