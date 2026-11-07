"""删空 BOM 撤销 pending 采购单：**备货来源**采购单的回归守卫。

2026-11-07 生产缺陷（PO-20261106-0003 / MINISO国际 / 23cm企鹅公仔(蓝色)）：
「一键生成」的备货来源采购单，`purchase_order.source_order_id` 与
`source_order_ids` **都是 NULL**，来源只写在 `purchase_order_sku` 快照里
（`source_order_id=87300, source_record_type='stockin'`）。

而撤销路径的精确判定 `fetch_po_sku_pids_map` 只从**主表**两字段解析来源：

    for po in orders:
        ids = _parse_source_order_ids(po)      # 本单 → 空集
    if not all_source_ids:
        return {po_id: [] for ...}             # 直接返回空

于是 `pids_map[po.id]` 恒为空 → `product_id in pids` 永不命中 → `revoked: 0`。
用户删空 BOM 后，采购单仍是 pending，工厂汇总里照常「可以正常下单」。

环境实证（`logs/后端(uvicorn).out.log`）：

    11:26:16 删空 BOM 撤销 pending 采购单: product_id=21158 {'revoked': 0, 'orders_reset': 0}
    11:27:13 删空 BOM 撤销 pending 采购单: product_id=21158 {'revoked': 0, 'orders_reset': 0}

同一函数对**客户订单来源**的产品（20909）是成功的（`revoked: 1`）——差别只在
「来源存在主表还是只存在快照里」。

修复：与工厂汇总 `purchase_order_query.get_factory_order_summary` 同款，用
**直接读快照表**的 `fetch_po_sku_map` + `_resolve_pids_from_sku_lines` 补一次
产品名反查，且只在「确有 pids 为空的单」时才发查询。
"""
from unittest.mock import AsyncMock, patch

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from fastapi_app.services.purchase_order_revoke import (
    revoke_pending_purchase_orders_for_product,
)
from fastapi_app.shared_models import Base, Product, PurchaseOrder, PurchaseOrderSku

PRODUCT_ID = 21158
PRODUCT_NAME = '23cm企鹅公仔(蓝色)'
PO_ID = 20508
STOCKIN_ID = 87300

_REVOKE_MOD = 'fastapi_app.services.purchase_order_revoke'


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    tables = [PurchaseOrder.__table__, PurchaseOrderSku.__table__, Product.__table__]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    maker = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _seed(db: AsyncSession, *, snapshot_product_name: str = PRODUCT_NAME) -> None:
    """一张「一键生成」的备货来源采购单：主表无来源，来源只在 sku 快照里。"""
    db.add(Product(id=PRODUCT_ID, name=PRODUCT_NAME))
    db.add(PurchaseOrder(
        id=PO_ID, order_no='PO-20261106-0003', customer_name='MINISO国际',
        product_name=PRODUCT_NAME, product_quantity=25000, supplier_name='美利达',
        status='pending', source_order_id=None, source_order_ids=None,
    ))
    db.add(PurchaseOrderSku(
        id=155, po_id=PO_ID, product_name=snapshot_product_name, order_qty=25000,
        source_order_id=STOCKIN_ID, source_record_type='stockin',
    ))
    await db.commit()


def _patched(revoke: AsyncMock):
    """外围全部打桩，只让「快照反查」这条真实 SQL 路径跑起来。"""
    return (
        patch(
            'fastapi_app.services.purchase._unprocessed._fetch_bom_product_ids',
            new=AsyncMock(return_value=set()),          # BOM 已删空
        ),
        patch(f'{_REVOKE_MOD}._product_source_ids', new=AsyncMock(return_value=[STOCKIN_ID])),
        patch(f'{_REVOKE_MOD}._candidate_pending_po_ids', new=AsyncMock(return_value={PO_ID})),
        patch(f'{_REVOKE_MOD}._revoke_targets', new=revoke),
    )


async def test_revoke_finds_stockin_sourced_po_via_sku_snapshot(db):
    """主表无 source_order_ids、来源只在快照 → 仍必须撤销该采购单。

    这是缺陷本体：修复前 `_revoke_targets` 收到的 targets 是空列表（revoked=0）。
    """
    await _seed(db)
    revoke = AsyncMock(return_value={'revoked': 1, 'orders_reset': 0})
    p1, p2, p3, p4 = _patched(revoke)
    with p1, p2, p3, p4:
        res = await revoke_pending_purchase_orders_for_product(db, PRODUCT_ID)

    assert res == {'revoked': 1, 'orders_reset': 0}
    revoke.assert_awaited_once()
    targets = revoke.await_args.args[1]
    assert [po.id for po in targets] == [PO_ID], '备货来源的采购单必须被识别为「含该产品」'


async def test_revoke_does_not_touch_po_for_another_product(db):
    """反向守卫：快照里的产品不是目标产品 → 不得误撤（防「按快照反查」变成误伤）。"""
    await _seed(db, snapshot_product_name='别的产品')
    revoke = AsyncMock(return_value={'revoked': 0, 'orders_reset': 0})
    p1, p2, p3, p4 = _patched(revoke)
    with p1, p2, p3, p4:
        res = await revoke_pending_purchase_orders_for_product(db, PRODUCT_ID)

    assert res == {'revoked': 0, 'orders_reset': 0}
    targets = revoke.await_args.args[1]
    assert targets == [], '快照产品名对不上时不得撤销任何单'


async def test_revoke_skips_snapshot_lookup_when_all_pos_have_pids(db):
    """非回归守卫：主表有来源（pids 非空）时**不得**多发一次快照查询。

    这条锁住 `any(not pids ...)` 这个条件——去掉它，普通客户订单来源的撤销路径
    会凭空多一次 SQL（并打乱按调用序列编排的既有 mock 测试）。
    """
    await _seed(db)
    revoke = AsyncMock(return_value={'revoked': 1, 'orders_reset': 0})
    fetch_sku = AsyncMock(return_value={})
    p1, p2, p3, p4 = _patched(revoke)
    with p1, p2, p3, \
         patch(
             'fastapi_app.services.purchase._common.fetch_po_sku_pids_map',
             new=AsyncMock(return_value={PO_ID: [PRODUCT_ID]}),
         ), \
         patch(
             'fastapi_app.services.purchase_order_sku.fetch_po_sku_map',
             new=fetch_sku,
         ), p4:
        res = await revoke_pending_purchase_orders_for_product(db, PRODUCT_ID)

    assert res == {'revoked': 1, 'orders_reset': 0}
    fetch_sku.assert_not_awaited()
