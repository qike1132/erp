"""订单明细删除/改量联动出货计划明细（2026-10-30 审计 A-M10）。

批量录单时若带分批出货计划，系统会按 remark「来源订单:{order_no}」同步出
采购/出货计划明细。整单删除早有级联清理，但**明细级**没有：

- 删掉某个 SKU → 计划里仍留着该 SKU 的分批数量，月历继续按它备料；
- 改某 SKU 数量 → 计划仍是旧数量，采购按旧量下单（超采购）。

修复：明细删除/改量时按「本订单 + 本 SKU」精确清理同步明细，被删空的主单一起删。
本文件锁定作用域（不能误删同客户其它订单/其它 SKU）与各调用点（A-M10：直改三路径；
H-1 2026-11-21：审批通过改量这条第四写路径）。
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.services import shipment_plan_sync
from fastapi_app.services.order import commands as order_commands


def _sql(stmt) -> str:
    return str(stmt.compile(compile_kwargs={'literal_binds': True}))


def _db(hit_rows=None):
    hit_result = MagicMock()
    hit_result.all.return_value = hit_rows if hit_rows is not None else []
    month_result = MagicMock()
    month_result.scalars.return_value.all.return_value = []
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[hit_result, month_result])
    return db


@pytest.mark.asyncio
async def test_sku_purge_scopes_by_order_and_product():
    rows = [MagicMock(id=11, plan_id=1)]
    db = _db(rows)
    db.execute = AsyncMock(side_effect=[_hit(rows), _months([]), _affected(1), _affected(0), _affected(0)])

    await shipment_plan_sync.purge_shipment_plan_details_for_sku(db, 'PO-1', 5)

    sql = _sql(db.execute.await_args_list[0].args[0])
    assert '来源订单:PO-1' in sql
    assert 'purchase_plan_details.product_id = 5' in sql


@pytest.mark.asyncio
async def test_sku_purge_without_product_is_noop():
    db = MagicMock()
    db.execute = AsyncMock()

    result = await shipment_plan_sync.purge_shipment_plan_details_for_sku(db, 'PO-1', None)

    assert result == {'detail_deleted': 0, 'plan_deleted': 0}
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_order_level_purge_stays_unscoped_by_product():
    """整单删除仍按订单清理全部 SKU，不能被 SKU 版本改变语义。"""
    db = MagicMock()
    empty = MagicMock()
    empty.all.return_value = []
    db.execute = AsyncMock(return_value=empty)

    await shipment_plan_sync.purge_shipment_plan_details_for_order(db, 'PO-2')

    sql = _sql(db.execute.await_args_list[0].args[0])
    assert '来源订单:PO-2' in sql
    assert 'product_id' not in sql


def _hit(rows):
    r = MagicMock()
    r.all.return_value = rows
    return r


def _months(months):
    r = MagicMock()
    r.scalars.return_value.all.return_value = months
    return r


def _affected(n):
    r = MagicMock()
    r.rowcount = n
    return r


# ============================================================================
# 调用点：明细改量 / 明细删除
# ============================================================================
def _head(order_id=1, product_id=5):
    r = MagicMock()
    r.one_or_none.return_value = MagicMock(order_id=order_id, product_id=product_id)
    return r


def _order(no='PO-1'):
    r = MagicMock()
    o = MagicMock()
    o.id = 1
    o.order_no = no
    o.is_deleted = False
    o.quantity = 100
    r.scalar_one_or_none.return_value = o
    return r


def _item(pid=5, qty=100):
    r = MagicMock()
    i = MagicMock()
    i.id = 11
    i.product_id = pid
    i.quantity = qty
    r.scalar_one_or_none.return_value = i
    return r


def _scalar(v):
    r = MagicMock()
    r.scalar_one.return_value = v
    return r


@pytest.mark.asyncio
async def test_update_order_item_purges_plan_details_on_quantity_change():
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[_head(), _order(), _item(), _scalar(120)])
    db.add = MagicMock()
    db.flush = AsyncMock()

    with patch.object(order_commands, 'get_product_for_update', new=AsyncMock()), \
         patch.object(order_commands, '_check_order_lock', new=AsyncMock()), \
         patch.object(order_commands, 'compute_order_status_from_db', new=AsyncMock(return_value='待备货')), \
         patch.object(order_commands, 'dispatch_factory_notifications', new=AsyncMock()), \
         patch.object(order_commands, 'cache_mgr', MagicMock(invalidate=AsyncMock())), \
         patch.object(order_commands, 'schedule_post_commit_invalidation'), \
         patch.object(order_commands, '_safe_invalidate_purchase_cache', new=AsyncMock()), \
         patch.object(order_commands, 'schedule_post_commit_event'), \
         patch.object(order_commands, '_purge_synced_plan_details', new=AsyncMock()) as m_purge:
        await order_commands.update_order_item(db, 11, 120, None, MagicMock(is_super=True))

    m_purge.assert_awaited_once()
    assert m_purge.await_args.args[1] == 'PO-1'
    assert m_purge.await_args.args[2] == 5


@pytest.mark.asyncio
async def test_update_order_item_does_not_purge_when_quantity_unchanged():
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[_head(), _order(), _item(qty=100), _scalar(100)])
    db.add = MagicMock()
    db.flush = AsyncMock()

    with patch.object(order_commands, 'get_product_for_update', new=AsyncMock()), \
         patch.object(order_commands, '_check_order_lock', new=AsyncMock()), \
         patch.object(order_commands, 'compute_order_status_from_db', new=AsyncMock(return_value='待备货')), \
         patch.object(order_commands, 'dispatch_factory_notifications', new=AsyncMock()), \
         patch.object(order_commands, 'cache_mgr', MagicMock(invalidate=AsyncMock())), \
         patch.object(order_commands, 'schedule_post_commit_invalidation'), \
         patch.object(order_commands, '_safe_invalidate_purchase_cache', new=AsyncMock()), \
         patch.object(order_commands, 'schedule_post_commit_event'), \
         patch.object(order_commands, '_purge_synced_plan_details', new=AsyncMock()) as m_purge:
        await order_commands.update_order_item(db, 11, 100, None, MagicMock(is_super=True))

    m_purge.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_order_item_purges_that_sku_only():
    """非末项删除：只清本 SKU 的同步明细，且必须带 order_no + product_id。"""
    order_res = _order()
    order_res.scalar_one_or_none.return_value.product_id = 9  # 兼容产品不是被删的那个
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[
        _head(order_id=1, product_id=5),   # head
        order_res,                          # 锁订单
        _scalar(0),                         # 已抵扣量
        _scalar(2),                         # 兄弟明细数（非末项）
        _item(pid=5, qty=30),               # 待删明细
        _scalar(0),                         # A-M9：外发流水数（0 → 放行）
        _scalar(90),                        # 剩余总量
    ])
    db.delete = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()

    with patch.object(order_commands, '_prelock_order_products', new=AsyncMock()), \
         patch.object(order_commands, '_check_order_lock', new=AsyncMock()), \
         patch.object(order_commands, 'compute_order_status_from_db', new=AsyncMock(return_value='待备货')), \
         patch.object(order_commands, 'dispatch_factory_notifications', new=AsyncMock()), \
         patch.object(order_commands, 'cache_mgr', MagicMock(invalidate=AsyncMock())), \
         patch.object(order_commands, 'schedule_post_commit_invalidation'), \
         patch.object(order_commands, '_safe_invalidate_purchase_cache', new=AsyncMock()), \
         patch.object(order_commands, 'schedule_post_commit_event'), \
         patch.object(order_commands, '_purge_synced_plan_details', new=AsyncMock()) as m_purge:
        await order_commands.delete_order_item(db, 11, MagicMock(is_super=True))

    m_purge.assert_awaited_once()
    assert m_purge.await_args.args[1] == 'PO-1'
    assert m_purge.await_args.args[2] == 5


@pytest.mark.asyncio
async def test_delete_order_item_rejects_when_outsource_ledger_exists():
    """A-M9：有外发发货/收货流水时，明细删除必须被拒（否则台账被 CASCADE 抹掉）。"""
    order_res = _order()
    order_res.scalar_one_or_none.return_value.product_id = 9
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[
        _head(order_id=1, product_id=5),
        order_res,
        _scalar(0),        # 抵扣量
        _scalar(2),        # 非末项
        _item(pid=5, qty=30),
        _scalar(3),        # 外发流水 3 条
    ])
    db.delete = AsyncMock()
    db.flush = AsyncMock()

    with patch.object(order_commands, '_prelock_order_products', new=AsyncMock()), \
         patch.object(order_commands, '_check_order_lock', new=AsyncMock()):
        with pytest.raises(ValueError, match='外发'):
            await order_commands.delete_order_item(db, 11, MagicMock(is_super=True))

    db.delete.assert_not_awaited()


# ============================================================================
# 调用点：审批通过改量（H-1，2026-11-21 审计）
# ============================================================================
def _edit_order(no='PO-1', product_id=5, quantity=100):
    o = MagicMock()
    o.id = 1
    o.order_no = no
    o.quantity = quantity
    o.customer = '客户A'
    o.note = ''
    o.is_locked = True
    o.locked_by_id = 7
    o.product_id = product_id
    return o


def _edit_approval(quantity):
    r = MagicMock()
    r.operation_data = json.dumps({'quantity': quantity, 'customer': '客户A'})
    return r


@pytest.mark.asyncio
async def test_approval_edit_purges_plan_details_on_quantity_change():
    """审批通过改量必须与直改三路径同口径：按「本订单 + 本 SKU」清理同步明细。

    拦的错（H-1）：非管理员提交「改数量」审批、管理员批准后，只写 InventoryLog +
    sync_single_item_quantity，不碰按 remark 溯源同步出的采购计划明细 → 月历/
    采购计划继续按旧量备料（超采购），与 A-M10 修直改路径前的后果逐字同源。
    """
    from fastapi_app.services import approval_service

    order = _edit_order()
    db = MagicMock()
    db.add = MagicMock()

    with patch.object(approval_service, 'get_product_for_update', new=AsyncMock()), \
         patch.object(approval_service, 'compute_order_status_from_db',
                      new=AsyncMock(return_value='待备货')), \
         patch.object(approval_service, 'sync_single_item_quantity', new=AsyncMock()), \
         patch.object(approval_service, 'purge_shipment_plan_details_for_sku',
                      new=AsyncMock(), create=True) as m_purge:
        await approval_service._handle_edit_approval(
            db, _edit_approval(120), order, MagicMock(id=99),
        )

    m_purge.assert_awaited_once()
    assert m_purge.await_args.args[1] == 'PO-1'
    assert m_purge.await_args.args[2] == 5


@pytest.mark.asyncio
async def test_approval_edit_does_not_purge_when_quantity_unchanged():
    """数量没变就不得清：纯改客户/备注的审批不能误触发计划明细清理。"""
    from fastapi_app.services import approval_service

    order = _edit_order()
    db = MagicMock()

    with patch.object(approval_service, 'get_product_for_update', new=AsyncMock()) as m_lock, \
         patch.object(approval_service, 'compute_order_status_from_db',
                      new=AsyncMock(return_value='待备货')), \
         patch.object(approval_service, 'sync_single_item_quantity', new=AsyncMock()), \
         patch.object(approval_service, 'purge_shipment_plan_details_for_sku',
                      new=AsyncMock(), create=True) as m_purge:
        await approval_service._handle_edit_approval(
            db, _edit_approval(100), order, MagicMock(id=99),
        )

    m_purge.assert_not_awaited()
    m_lock.assert_not_awaited()
