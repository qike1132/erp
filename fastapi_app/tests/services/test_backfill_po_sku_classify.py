"""FIX-7 回归：回填脚本把「源记录缺失」与「数值不一致」显式分类，且源缺失不写任何行。

被验证行为（``scripts/backfill_purchase_order_sku.py::_plan_for_po``）：
- 来源记录存在            → kind=_DERIVED（rows 非空，参与后续 Σ vs 主表对账）；
- 有 source_order_ids 但来源记录不存在 → kind=_SOURCE_MISSING，**rows 为空**（绝不静默写 0 值行，
  读路径据此降级为订单级），并回传缺失 id 列表用于报告；
- source_order_ids 为空   → kind=_NO_SOURCE_IDS，rows 为空。

这样 dry-run 输出可把「脏数据（源缺失）」与「算法错（数值不一致）」分开计数。
"""
import importlib.util
from datetime import datetime
from pathlib import Path

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from fastapi_app.shared_models import (
    Base,
    Order,
    OrderItem,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderStatus,
    StockIn,
    User,
)

_SCRIPT_PATH = Path(r"D:\erp_system\scripts\backfill_purchase_order_sku.py")


def _load_script_module():
    """按文件路径加载回填脚本（`scripts` 非包，避免依赖 sys.path 布局）。"""
    spec = importlib.util.spec_from_file_location("_bf_po_sku", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_bf = _load_script_module()

_TABLES = [
    User.__table__, Product.__table__, Order.__table__, OrderItem.__table__,
    StockIn.__table__, PurchaseOrder.__table__, PurchaseOrderItem.__table__,
]


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=_TABLES))
    maker = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def test_plan_derived_when_source_present(db):
    """来源记录存在 → 派生成功（_DERIVED），rows 非空、Σ 可对账。"""
    db.add(Product(id=1, name='A', barcode='bA'))
    db.add(Order(
        id=11, order_no='PO-011', customer='客户A',
        order_date=datetime(2026, 9, 1, 10, 0, 0), product_id=1, quantity=10,
        items=[OrderItem(product_id=1, product_name='A', product_barcode='bA', quantity=10)],
    ))
    await db.commit()

    po = PurchaseOrder(
        id=1, order_no='PC-1', status=PurchaseOrderStatus.COMPLETED,
        product_name='A', product_quantity=10, source_order_ids='[11]', spare_rate=50,
    )
    rows, total, kind, missing = await _bf._plan_for_po(db, po)

    assert kind == _bf._DERIVED
    assert len(rows) == 1
    assert total == 10
    assert rows[0]['order_qty'] == 10
    assert missing == []


async def test_plan_source_missing_yields_no_rows(db):
    """source_order_ids 指向的记录不存在 → _SOURCE_MISSING 且 rows 为空（不写 0 值行）。"""
    po = PurchaseOrder(
        id=2, order_no='PC-2', status=PurchaseOrderStatus.COMPLETED,
        product_name='X', product_quantity=999, source_order_ids='[9999]', spare_rate=None,
    )
    rows, total, kind, missing = await _bf._plan_for_po(db, po)

    assert kind == _bf._SOURCE_MISSING
    assert rows == [], '源记录缺失时不得写入任何逐 SKU 行（尤其不得写 0 值行）'
    assert total == 0.0
    assert missing == [9999]


async def test_plan_no_source_ids(db):
    """source_order_ids 为空 → _NO_SOURCE_IDS 且 rows 为空。"""
    po = PurchaseOrder(
        id=3, order_no='PC-3', status=PurchaseOrderStatus.COMPLETED,
        product_name='Y', product_quantity=5, source_order_ids=None, spare_rate=None,
    )
    rows, total, kind, missing = await _bf._plan_for_po(db, po)

    assert kind == _bf._NO_SOURCE_IDS
    assert rows == []
    assert missing == []


async def test_plan_classification_is_stable_across_calls(db):
    """dry-run 幂等前提：同一输入两次调用分类与派生完全一致。"""
    po = PurchaseOrder(
        id=4, order_no='PC-4', status=PurchaseOrderStatus.COMPLETED,
        product_name='Z', product_quantity=7, source_order_ids='[8888]', spare_rate=None,
    )
    first = await _bf._plan_for_po(db, po)
    second = await _bf._plan_for_po(db, po)
    assert first == second
