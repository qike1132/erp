"""湖北订单搜索态下的「逐 order_item 真实数量」回归测试（缺陷 #4）。

背景：产品筛选（product_kw）生效时，`_build_beile_order_record` 会把 items 收窄为
命中的 SKU，并把行 `quantity` 改成「首个命中 SKU 的量」。未命中 SKU 的外发工序同样
挂在整单上，前端若拿行 quantity 给它们兜底，目标量就会取到别的 SKU 的量：
偏大 → 一键发货整批 400；偏小 → 静默少发。

修复：行内新增 `item_qty_map`（{order_item_id: 数量}，覆盖收窄前的全部工厂 SKU），
既有字段语义一概不动。本测试拦的就是「收窄后拿不到未命中 SKU 的真实数量」。
"""
from __future__ import annotations

from datetime import datetime

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from fastapi_app.core.cache import invalidate_cache
from fastapi_app.services.order.beile import get_beile_orders_with_stockins
from fastapi_app.shared_models import (
    Base,
    Notification,
    Order,
    OrderItem,
    Product,
    PurchaseOrder,
    StockIn,
    User,
)


@pytest_asyncio.fixture
async def db():
    """真实模型的 sqlite 内存库会话（表集合同 test_beile_orders.py）。

    - UNION 查询同时扫 order / stockin，两张表都必须存在；
    - completed 采购单映射读 purchase_order（缺表直接 OperationalError）；
    - 未确认计数读 notification；
    - beile-list 带 60s L2 缓存且 key 不含数据指纹，跨用例存活会让本用例读到
      上一个用例的串号结果（假红），故每个用例开始前失效缓存。
    """
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    tables = [
        User.__table__, Product.__table__, Order.__table__, OrderItem.__table__,
        StockIn.__table__, Notification.__table__, PurchaseOrder.__table__,
    ]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    maker = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    await invalidate_cache('orders:beile:*')
    async with maker() as session:
        yield session
    await engine.dispose()


async def _seed_multi_sku_order(db: AsyncSession) -> tuple[int, int, int]:
    """一张湖北订单两个 SKU：「变形金刚」60 +「蛋黄派」40。

    Returns:
        (命中 SKU 的 order_item id, 未命中 SKU 的 order_item id, 订单 id)
    """
    p1 = Product(id=1, name='变形金刚', barcode='690001', factory='湖北')
    p2 = Product(id=2, name='蛋黄派', barcode='690002', factory='湖北')
    order = Order(
        id=15, order_no='PO-015', customer='多SKU客户',
        order_date=datetime(2026, 9, 5, 10, 0, 0), product_id=1, quantity=100,
        items=[
            OrderItem(product_id=1, product_name='变形金刚', product_barcode='690001', quantity=60),
            OrderItem(product_id=2, product_name='蛋黄派', product_barcode='690002', quantity=40),
        ],
    )
    db.add_all([User(id=1, username='hubei_op', password='x', factory='湖北'), p1, p2, order])
    await db.commit()

    by_name = {it.product_name: it.id for it in order.items}
    return by_name['变形金刚'], by_name['蛋黄派'], order.id


async def test_search_narrowed_row_still_carries_other_sku_qty(db):
    """product_kw 只命中一个 SKU 时，未命中 SKU 的真实数量仍要带出来。

    拦哪种错：收窄后 items 只剩命中 SKU，行 quantity = 首个命中 SKU 的量（60），
    未命中 SKU（40）若无处可取，前端就会把 60 当成它的工序目标量。
    """
    hit_id, miss_id, order_id = await _seed_multi_sku_order(db)

    result = await get_beile_orders_with_stockins(
        db, page=1, per_page=50, customer='多SKU客户', product_kw='变形金刚',
    )
    row = next(r for r in result['items'] if r['record_type'] == 'order' and r['id'] == order_id)

    # 既有语义不变：items 收窄为命中 SKU，行 quantity 仍是首个命中 SKU 的量
    assert [it['product_name'] for it in row['items']] == ['变形金刚']
    assert row['quantity'] == 60

    # 新增字段：两个 SKU 的真实数量都在，未命中 SKU 的量与命中 SKU 不同
    qty_map = row['item_qty_map']
    assert qty_map[str(hit_id)] == 60
    assert qty_map[str(miss_id)] == 40
    assert qty_map[str(miss_id)] != qty_map[str(hit_id)]


async def test_item_qty_map_matches_unsarched_row(db):
    """防回归：无关键字时映射与全量 items 一致，收窄与否都不改变真实数量。"""
    hit_id, miss_id, order_id = await _seed_multi_sku_order(db)

    result = await get_beile_orders_with_stockins(db, page=1, per_page=50, customer='多SKU客户')
    row = next(r for r in result['items'] if r['record_type'] == 'order' and r['id'] == order_id)

    assert [it['product_name'] for it in row['items']] == ['变形金刚', '蛋黄派']
    assert row['item_qty_map'] == {str(hit_id): 60, str(miss_id): 40}
