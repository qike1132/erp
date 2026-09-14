"""湖北订单+备货合并查询与确认（services/order/beile.py）服务层回归测试。

使用 sqlite+aiosqlite 内存库 + 真实模型，覆盖：
- UNION 合并列表的字段结构与 record_type 区分（product_image 已下线）
- confirm_status / product_kw 筛选（订单按 SKU、备货按产品）
- 同秒记录的稳定排序（record_type, source_id 次级排序键）
- 页码越界回退（LIMIT 1 窗口 count 探测总数）
- 确认流程：幂等、非湖北 404 隔离、未读通知批量标记已读
"""
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from fastapi_app.core.exceptions import NotFoundError
from fastapi_app.services.notification_service import BEILE_UNCONFIRMED_TYPE
from fastapi_app.services.order.beile import (
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
    StockIn,
    User,
)


@pytest_asyncio.fixture
async def db():
    """真实模型的 sqlite 内存库会话（每个测试独立实例）。

    仅建本测试涉及的表：全量 metadata 含 PG 专用类型（JSONB 等），sqlite 无法编译。
    """
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    tables = [
        User.__table__, Product.__table__, Order.__table__,
        OrderItem.__table__, StockIn.__table__, Notification.__table__,
    ]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    maker = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _seed(db: AsyncSession) -> User:
    """构造湖北/东莞混合的订单+备货+通知数据。

    期望的 beile-list（无筛选、按日期倒序）：
        o2(9/2 10:00 订单) → s1(9/2 10:00 备货，与 o2 同秒，tiebreaker 订单在前)
        → o1(9/1) → o4(8/30，已确认) → s2(7/1，已确认)
    o3/s3 属东莞工厂，不出现。
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

    notification = Notification(user_id=1, type=BEILE_UNCONFIRMED_TYPE, title='待确认提醒',
                                content='{}', related_order_id=11, is_read=False)

    db.add_all([user, p1, p2, p3, o1, o2, o3, o4, s1, s2, s3, notification])
    await db.commit()
    return user


async def test_beile_list_merged_sorted_and_shaped(db):
    await _seed(db)
    result = await get_beile_orders_with_stockins(db, page=1, per_page=50)

    # 东莞的订单/备货被排除，其余 5 条按日期倒序、同秒 tiebreaker 订单在前
    assert [(r['record_type'], r['id']) for r in result['items']] == [
        ('order', 12), ('stockin', 21), ('order', 11), ('order', 14), ('stockin', 22),
    ]
    assert result['total'] == 5
    assert result['unconfirmed_count'] == 3  # 未确认：o1/o2/s1（o4/s2 已确认，o3/s3 非湖北）

    first = result['items'][0]
    assert first['order_no'] == 'PO-012'
    assert first['customer'] == '客户B'
    assert first['factories'] == ['湖北']
    assert first['confirmed'] is False
    assert first['items'][0]['product_barcode'] == '690002'
    # product_image 已随惰性加载风险一并下线，不应再出现在响应中
    assert 'product_image' not in first
    assert 'product_image' not in result['items'][1]  # stockin 记录


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
