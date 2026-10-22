"""Z02-R4：撤销「删空 BOM 产品的 pending 采购单」不得再全量加载 pending 单。

审计处方：先经 ``purchase_order_sku`` 表 SQL join 反查含该产品的 po_id 集合，
再按 id 集合精准加载目标单。旧实现是 ``select(PurchaseOrder).where(status ==
PENDING)`` 全量载入实体再逐单反推产品归属，pending 越多越慢。

本文件用「按 SQL 文本路由」的假会话钉住两件事：

1. 实现**不得**再发出「无 id 限制的 pending 全量加载」查询（``full_pending_loads``）；
2. 收窄之后撤销结果与旧实现一致，且**无快照行的历史 pending 单**仍会被撤销
   （快照表是迁移 047 之后才有的，历史单只有采购单自身的来源字段）。
"""
from __future__ import annotations

import re
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.dialects import postgresql

from fastapi_app.services.purchase_order_revoke import (
    _candidate_pending_po_ids,
    _product_source_ids,
    revoke_pending_purchase_orders_for_product,
)

TARGET_PRODUCT = 20909
OTHER_PRODUCT = 99999
SOURCE_ORDER = 68939
OTHER_ORDER = 68940


def _sql(stmt) -> str:
    if isinstance(stmt, str):
        return stmt
    return str(stmt.compile(
        dialect=postgresql.dialect(), compile_kwargs={'literal_binds': True},
    ))


def _in_ids(sql: str, column: str) -> set[int]:
    match = re.search(rf'{re.escape(column)} IN \(([^)]*)\)', sql)
    if not match:
        return set()
    return {int(part) for part in match.group(1).split(',') if part.strip()}


class _Scalars:
    def __init__(self, items):
        self._items = items

    def unique(self):
        return self

    def all(self):
        return self._items


class _Result:
    def __init__(self, *, scalars=None, rows=None):
        self._scalars = scalars or []
        self._rows = rows or []

    def scalars(self):
        return _Scalars(self._scalars)

    def unique(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _BeginNested:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


class _FakeSession:
    """按 SQL 文本路由的假会话。

    ``full_pending_loads`` 记录「无 id 限制的 pending 全量加载」次数——那是 Z02-R4
    要消灭的反模式；旧实现在这里会 +1。
    """

    def __init__(self, *, pending_pos, order_items=(), orders=(), stockins=(),
                 snapshot_po_ids=(), legacy_rows=(), source_order_rows=(),
                 source_orders=()):
        self.info = {}
        self.statements: list[str] = []
        self.full_pending_loads = 0
        self._pending_pos = list(pending_pos)
        self._order_items = list(order_items)
        self._orders = list(orders)
        self._stockins = list(stockins)
        self._snapshot_po_ids = list(snapshot_po_ids)
        self._legacy_rows = list(legacy_rows)
        self._source_order_rows = list(source_order_rows)
        self._source_orders = list(source_orders)

    def begin_nested(self):
        return _BeginNested()

    async def flush(self):
        return None

    async def execute(self, stmt):
        sql = _sql(stmt)
        self.statements.append(sql)
        return self._route(sql)

    def _route(self, sql: str) -> _Result:
        if 'purchase_order_sku LIMIT 1' in sql:      # po_sku_available 探针
            return _Result()
        if 'FROM order_item' in sql:
            match = re.search(r'order_item\.product_id = (\d+)', sql)
            if match:                                 # 按产品反查来源订单
                pid = int(match.group(1))
                return _Result(scalars=[oid for oid, opid in self._order_items if opid == pid])
            return _Result(rows=self._order_items)   # 逐 SKU 映射
        if 'FROM stock_in' in sql:
            match = re.search(r'stock_in\.product_id = (\d+)', sql)
            if match:
                pid = int(match.group(1))
                return _Result(scalars=[sid for sid, spid in self._stockins if spid == pid])
            return _Result(rows=self._stockins)
        if 'FROM "order"' in sql:
            match = re.search(r'"order"\.product_id = (\d+)', sql)
            if match:                                 # 订单兼容字段回退
                pid = int(match.group(1))
                return _Result(scalars=[oid for oid, opid in self._orders if opid == pid])
            return _Result(scalars=list(self._source_orders))
        if 'FROM purchase_order_sku' in sql:
            if 'NOT (EXISTS' in sql:                   # 无快照行的历史 pending 单
                return _Result(rows=self._legacy_rows)
            if 'purchase_order.id IN (SELECT' in sql:  # 快照表反查候选 po_id
                return _Result(rows=[(pid,) for pid in self._snapshot_po_ids])
            return _Result(rows=self._source_order_rows)
        if 'FROM purchase_order' in sql:
            ids = _in_ids(sql, 'purchase_order.id')
            if ids:
                return _Result(scalars=[po for po in self._pending_pos if po.id in ids])
            self.full_pending_loads += 1               # 反模式：无限制全量加载
            return _Result(scalars=list(self._pending_pos))
        return _Result()


def _make_po(po_id: int, source_ids: str):
    po = MagicMock()
    po.id = po_id
    po.source_order_id = None
    po.source_order_ids = source_ids
    return po


def _patched(delete_po):
    return (
        patch('fastapi_app.services.purchase._unprocessed._fetch_bom_product_ids',
              new=AsyncMock(return_value=set())),
        patch('fastapi_app.services.purchase_order_crud.delete_purchase_order', new=delete_po),
        patch('fastapi_app.services.order_utils.compute_order_statuses_batch',
              new=AsyncMock(return_value={SOURCE_ORDER: '待备货'})),
    )


async def test_revoke_narrows_pending_po_load_to_candidates():
    """核心：只按候选 po_id 加载 pending 单，不再全量载入实体。"""
    po_hit = _make_po(501, '[68939]')
    po_other = _make_po(502, '[68940]')
    order_obj = MagicMock()
    order_obj.id = SOURCE_ORDER
    order_obj.status = '已备货'

    db = _FakeSession(
        pending_pos=[po_hit, po_other],
        order_items=[(SOURCE_ORDER, TARGET_PRODUCT), (OTHER_ORDER, OTHER_PRODUCT)],
        snapshot_po_ids=[501],
        source_order_rows=[(501, SOURCE_ORDER)],
        source_orders=[order_obj],
    )
    delete_po = AsyncMock()

    bom_patch, delete_patch, status_patch = _patched(delete_po)
    with bom_patch, delete_patch, status_patch:
        res = await revoke_pending_purchase_orders_for_product(db, TARGET_PRODUCT)

    assert res == {'revoked': 1, 'orders_reset': 1}, res
    assert db.full_pending_loads == 0, '不得出现无 id 限制的 pending 全量加载'
    delete_po.assert_awaited_once_with(db, 501)      # 只撤覆盖该产品的那张
    assert order_obj.status == '待备货', '来源订单应被重算回待备货'
    # 审计处方：候选集必须来自 purchase_order_sku 的 SQL 反查
    assert any('purchase_order_sku' in s and 'source_order_id IN' in s
               for s in db.statements), '缺少经快照表反查 po_id 的 SQL'


async def test_revoke_keeps_legacy_pending_po_without_snapshot_rows():
    """历史 pending 单（无快照行）仍按采购单自身来源字段被撤销。"""
    po_legacy = _make_po(601, '[68939]')
    order_obj = MagicMock()
    order_obj.id = SOURCE_ORDER
    order_obj.status = '已备货'

    db = _FakeSession(
        pending_pos=[po_legacy],
        order_items=[(SOURCE_ORDER, TARGET_PRODUCT)],
        snapshot_po_ids=[],                          # 快照表反查不到
        legacy_rows=[(601, None, '[68939]')],        # 无快照行的历史单
        source_order_rows=[(601, SOURCE_ORDER)],
        source_orders=[order_obj],
    )
    delete_po = AsyncMock()

    bom_patch, delete_patch, status_patch = _patched(delete_po)
    with bom_patch, delete_patch, status_patch:
        res = await revoke_pending_purchase_orders_for_product(db, TARGET_PRODUCT)

    assert res == {'revoked': 1, 'orders_reset': 1}, res
    delete_po.assert_awaited_once_with(db, 601)
    assert db.full_pending_loads == 0


async def test_revoke_does_not_touch_pending_pos_of_other_products():
    """候选集之外的 pending 单（别家产品）不受影响。"""
    po_other = _make_po(502, '[68940]')
    order_obj = MagicMock()
    order_obj.id = OTHER_ORDER
    order_obj.status = '已备货'

    db = _FakeSession(
        pending_pos=[po_other],
        order_items=[(OTHER_ORDER, OTHER_PRODUCT)],
        snapshot_po_ids=[],                          # 快照表反查不到该产品
        source_order_rows=[],
        source_orders=[order_obj],
    )
    delete_po = AsyncMock()

    bom_patch, delete_patch, status_patch = _patched(delete_po)
    with bom_patch, delete_patch, status_patch:
        res = await revoke_pending_purchase_orders_for_product(db, TARGET_PRODUCT)

    assert res == {'revoked': 0, 'orders_reset': 0}, res
    delete_po.assert_not_awaited()
    assert db.full_pending_loads == 0


async def test_product_source_ids_cover_order_item_order_and_stockin():
    """来源 id 集合 = order_item ∪ order ∪ stock_in（回退链的超集）。"""
    db = _FakeSession(
        pending_pos=[],
        order_items=[(SOURCE_ORDER, TARGET_PRODUCT)],
        orders=[(70001, TARGET_PRODUCT)],
        stockins=[(80001, TARGET_PRODUCT)],
    )
    assert await _product_source_ids(db, TARGET_PRODUCT) == [68939, 70001, 80001]


async def test_candidate_ids_empty_when_no_source_records():
    """产品没有任何来源记录 → 候选集为空，不加载任何采购单。"""
    db = _FakeSession(pending_pos=[])
    assert await _candidate_pending_po_ids(db, []) == set()
    assert db.full_pending_loads == 0
