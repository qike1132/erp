"""撤销链与自动生成侧共用 `PURCHASE_GENERATE_SOURCE` advisory lock 的回归守卫。

缺陷本体：「删空 BOM 撤销」与「并发保存 BOM 触发自动生成」可交错 —— 生成侧在
`purchase_order_generate` 里经 `acquire_source_locks` 取来源锁，撤销侧此前**一把不取**，
于是撤销「确认已删空」之后，生成侧仍可越过检查按旧 BOM 落一张引用空 BOM 的
pending 孤儿单。

本文件只钉两件事：
1. `revoke_pending_purchase_orders_for_product` 会为**裸 id 对应的两种来源类型**
   都取锁（`order:{id}` 与 `stockin:{id}`），且锁取在候选单查询**之前**；
2. `revoke_pending_purchase_orders_for_{order,stockin}` 经 `_revoke_by_source` 按
   typed id 取锁（`order:{id}` / `stockin:{id}`），不混用裸 id。

不需要真实数据库：db 用 `AsyncMock`，撤销主体（`_revoke_targets`）与外围查询全部打桩，
只留「取锁 + 编排」这段真实代码。
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.services.purchase_order_revoke import (
    revoke_pending_purchase_orders_for_order,
    revoke_pending_purchase_orders_for_product,
    revoke_pending_purchase_orders_for_stockin,
)

REVOKE_MOD = 'fastapi_app.services.purchase_order_revoke'
IDEMPOTENCY_MOD = 'fastapi_app.services.purchase_order_idempotency'
UNPROCESSED_MOD = 'fastapi_app.services.purchase._unprocessed'


def _empty_execute_result() -> MagicMock:
    """`db.execute(...)` 的返回值：`.all()` 为空 → 「没有命中快照行」。"""
    result = MagicMock()
    result.all.return_value = []
    return result


def _db_with_no_rows() -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_empty_execute_result())
    return db


def _lock_recorder(events: list) -> AsyncMock:
    async def _lock(_db, composite_ids):
        events.append(('lock', list(composite_ids)))

    return AsyncMock(side_effect=_lock)


# ============================================================================
# 删空 BOM 撤销：两种来源类型都锁
# ============================================================================
async def test_product_revoke_locks_both_source_types_before_candidate_query() -> None:
    """`_product_source_ids` 给的是裸 id（order/stockin 会撞号）→ 两类锁都要取。"""
    events: list[tuple] = []

    async def _candidates(_db, source_ids):
        events.append(('candidates', list(source_ids)))
        return set()  # 无候选单 → 取锁后即返回，不触碰真实 SQL

    db = _db_with_no_rows()
    with patch(f'{UNPROCESSED_MOD}._fetch_bom_product_ids', new=AsyncMock(return_value=set())), \
         patch(f'{REVOKE_MOD}._product_source_ids', new=AsyncMock(return_value=[1])), \
         patch(f'{REVOKE_MOD}._candidate_pending_po_ids', new=AsyncMock(side_effect=_candidates)), \
         patch(f'{IDEMPOTENCY_MOD}.acquire_source_locks', new=_lock_recorder(events)):
        result = await revoke_pending_purchase_orders_for_product(db, 42)

    assert result == {'revoked': 0, 'orders_reset': 0}
    lock_calls = [payload for kind, payload in events if kind == 'lock']
    assert len(lock_calls) == 1, f'应当只取一批来源锁，实际 {lock_calls}'
    assert 'order:1' in lock_calls[0]
    assert 'stockin:1' in lock_calls[0]
    # 锁序：advisory 锁必须在任何查询/行锁/删除之前取（否则窗口仍在，锁等于没取）
    assert [kind for kind, _payload in events] == ['lock', 'candidates']


async def test_product_revoke_locks_every_source_id_for_both_types() -> None:
    """每个裸 id 都要落两类锁（多锁一类只降并发，不误伤；漏锁才留孤儿单）。"""
    events: list[tuple] = []
    db = _db_with_no_rows()
    with patch(f'{UNPROCESSED_MOD}._fetch_bom_product_ids', new=AsyncMock(return_value=set())), \
         patch(f'{REVOKE_MOD}._product_source_ids', new=AsyncMock(return_value=[7, 9])), \
         patch(f'{REVOKE_MOD}._candidate_pending_po_ids', new=AsyncMock(return_value=set())), \
         patch(f'{IDEMPOTENCY_MOD}.acquire_source_locks', new=_lock_recorder(events)):
        await revoke_pending_purchase_orders_for_product(db, 42)

    assert len(events) == 1 and events[0][0] == 'lock'
    # 锁键集合（顺序无关：`acquire_source_locks` 内部自己排序，两侧锁序一致即无 AB-BA）
    assert set(events[0][1]) == {'order:7', 'stockin:7', 'order:9', 'stockin:9'}


async def test_product_revoke_skips_locks_when_no_sources() -> None:
    """没有来源记录时不取锁（不加无意义的全局串行点）。"""
    db = _db_with_no_rows()
    locks = AsyncMock()
    with patch(f'{UNPROCESSED_MOD}._fetch_bom_product_ids', new=AsyncMock(return_value=set())), \
         patch(f'{REVOKE_MOD}._product_source_ids', new=AsyncMock(return_value=[])), \
         patch(f'{REVOKE_MOD}._candidate_pending_po_ids', new=AsyncMock(return_value=set())), \
         patch(f'{IDEMPOTENCY_MOD}.acquire_source_locks', new=locks):
        result = await revoke_pending_purchase_orders_for_product(db, 42)

    assert result == {'revoked': 0, 'orders_reset': 0}
    locks.assert_not_awaited()


async def test_product_revoke_with_bom_left_takes_no_lock() -> None:
    """BOM 未删空时本函数直接返回，不取锁（避免给正常保存 BOM 加锁开销）。"""
    db = _db_with_no_rows()
    locks = AsyncMock()
    with patch(f'{UNPROCESSED_MOD}._fetch_bom_product_ids', new=AsyncMock(return_value={99})), \
         patch(f'{REVOKE_MOD}._product_source_ids', new=AsyncMock(return_value=[1])), \
         patch(f'{IDEMPOTENCY_MOD}.acquire_source_locks', new=locks):
        result = await revoke_pending_purchase_orders_for_product(db, 42)

    assert result == {'revoked': 0, 'orders_reset': 0}
    locks.assert_not_awaited()


# ============================================================================
# 按来源记录撤销：typed id 取锁
# ============================================================================
@pytest.mark.parametrize(
    ('func', 'expected_lock'),
    [
        (revoke_pending_purchase_orders_for_order, 'order:123'),
        (revoke_pending_purchase_orders_for_stockin, 'stockin:123'),
    ],
    ids=['order', 'stockin'],
)
async def test_revoke_by_source_takes_typed_lock(func, expected_lock: str) -> None:
    """撤销必须按 typed id 取锁，与生成侧锁键逐字一致（裸 id 对不上就白锁）。"""
    events: list[tuple] = []
    db = _db_with_no_rows()  # 快照里查不到行 → po_ids 为空，取锁后提前返回

    with patch(f'{IDEMPOTENCY_MOD}.acquire_source_locks', new=_lock_recorder(events)):
        result = await func(db, 123)

    assert result == {'revoked': 0, 'orders_reset': 0}
    assert events == [('lock', [expected_lock])]
