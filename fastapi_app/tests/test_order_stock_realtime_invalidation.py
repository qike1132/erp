"""订单写路径：改明细/订单必须失效库存缓存并在提交后广播 ORDER_UPDATED（回归守卫）

缺陷背景（2026-10-31 实测）：/report 行内把订单明细数量 10000 改成 1000 后，
/stock 的订单数量约 20~30 秒才更新。初判为「后端没失效 inventory 缓存」——复核后
**后端链路自 2026-10-13（4d7cad54）起是完整的**（生产日志亦证实编辑后打出了
`Redis 缓存失效: pattern=inventory:*`），真根因在前端 refreshAfterWrite 只失效
report-data（见 useReportRowActions 的 vitest）。

本文件锁死后端两条不变量，防止未来重构（尤其 commands.py 拆分/写路径增改）时
静默丢掉任一环节：
  1. update_order_item / update_order（直改分支）必须失效 ORDER_AND_INVENTORY 域
     （含 inventory:* 与 product:list），且安排 post-commit 兜底失效；
  2. ORDER_UPDATED 事件走 schedule_post_commit_event（提交后才广播，不许在事务内发），
     type 与前端 /stock 的 WS 订阅名 'order_updated' 一致。

mock 形状与 test_shipment_plan_sku_purge.py 同款（update_order_item 的 execute
调用序：head → 锁单 → 锁 item → SUM 总量）。
"""
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.core.cache import CacheDomain
from fastapi_app.services.notification_service import StockEvent
from fastapi_app.services.order import commands as order_commands


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
    o.product_id = 5
    r.scalar_one_or_none.return_value = o
    return r


def _item(pid=5, qty=100):
    r = MagicMock()
    i = MagicMock()
    i.id = 11
    i.product_id = pid
    i.quantity = qty
    i.note = ''
    r.scalar_one_or_none.return_value = i
    return r


def _scalar(v):
    r = MagicMock()
    r.scalar_one.return_value = v
    return r


def _recorder(into: list):
    """记录器：同步/异步通用——把位置参数以 tuple 存入 into（patch.object 的 side_effect）"""
    def _rec(*args, **kwargs):
        into.append(args)
    return _rec


def _patched_write_path(invalidate: Any, sched_invalid: Any, sched_event: Any):
    """update_order_item / delete_order_item 共用的写路径桩集合。
    schedule_post_commit_* 是同步函数，用普通函数记录器（AsyncMock 会吞掉真实调用时序）。"""
    return (
        patch.object(order_commands, 'get_product_for_update', new=AsyncMock()),
        patch.object(order_commands, '_check_order_lock', new=AsyncMock()),
        patch.object(order_commands, 'compute_order_status_from_db',
                     new=AsyncMock(return_value='待备货')),
        patch.object(order_commands, 'dispatch_factory_notifications', new=AsyncMock()),
        patch.object(order_commands, 'cache_mgr',
                     MagicMock(invalidate=AsyncMock(side_effect=invalidate))),
        patch.object(order_commands, 'schedule_post_commit_invalidation', side_effect=sched_invalid),
        patch.object(order_commands, '_safe_invalidate_purchase_cache', new=AsyncMock()),
        patch.object(order_commands, 'schedule_post_commit_event', side_effect=sched_event),
        patch.object(order_commands, '_purge_synced_plan_details', new=AsyncMock()),
    )


@pytest.mark.asyncio
async def test_update_order_item_invalidates_inventory_domain():
    """(a) 改明细数量必须失效 ORDER_AND_INVENTORY|REPORT（含 /stock 的 inventory:* 缓存）"""
    invalidate_calls: list = []
    sched_invalid_calls: list = []

    db = MagicMock()
    db.execute = AsyncMock(side_effect=[_head(), _order(), _item(qty=100), _scalar(120)])
    db.add = MagicMock()
    db.flush = AsyncMock()

    patches = _patched_write_path(
        _recorder(invalidate_calls), _recorder(sched_invalid_calls), lambda *a, **k: None)
    with patches[0], patches[1], patches[2], patches[3], patches[4], \
         patches[5], patches[6], patches[7], patches[8]:
        await order_commands.update_order_item(db, 11, 120, None, MagicMock(is_super=True))

    assert invalidate_calls, 'update_order_item 未失效任何缓存域（/stock 将最长 120s 旧数据）'
    # invalidate 的调用参数：(InvalidationStrategy.DOMAIN, ORDER_AND_INVENTORY | REPORT)
    # ORDER_AND_INVENTORY 必含 INVENTORY 位 —— inventory:* 是 /stock 的缓存键前缀
    domains = [call[1] for call in invalidate_calls if len(call) > 1]
    assert any(d & CacheDomain.INVENTORY for d in domains), \
        f'失效域未覆盖 INVENTORY: {domains}（/stock 的 inventory:* 缓存不会清除）'
    # sched_invalid: 提交后兜底失效必须被注册（防「提交前失效被并发回填」竞态）
    assert sched_invalid_calls, 'update_order_item 未安排 post-commit 兜底失效'


@pytest.mark.asyncio
async def test_update_order_item_schedules_order_updated_after_commit():
    """(b)+(c) ORDER_UPDATED 走 schedule_post_commit_event（post-commit 才广播），
    type 必须与前端 /stock 的 WS 订阅名 'order_updated' 一致。"""
    sched_event_calls: list = []

    db = MagicMock()
    db.execute = AsyncMock(side_effect=[_head(), _order(), _item(qty=100), _scalar(120)])
    db.add = MagicMock()
    db.flush = AsyncMock()

    patches = _patched_write_path(
        lambda *a, **k: None, lambda *a, **k: None, _recorder(sched_event_calls))
    with patches[0], patches[1], patches[2], patches[3], patches[4], \
         patches[5], patches[6], patches[7], patches[8]:
        await order_commands.update_order_item(db, 11, 120, None, MagicMock(is_super=True))

    assert sched_event_calls, 'update_order_item 未注册 ORDER_UPDATED 事件（/stock WS 永不触发）'
    # schedule_post_commit_event(db, event_type, data)：[0]=db、[1]=事件类型
    event_type = sched_event_calls[0][1]
    assert event_type == StockEvent.ORDER_UPDATED == 'order_updated', \
        f'事件类型 {event_type!r} 与前端订阅名不一致'


@pytest.mark.asyncio
async def test_update_order_admin_direct_path_invalidates_and_publishes():
    """update_order 超管直改分支（_update_order_directly）同口径：失效 + post-commit 事件"""
    invalidate_calls: list = []
    sched_event_calls: list = []

    product = MagicMock()
    product.id = 5

    db = MagicMock()
    # update_order 的 execute 序：product_id 预读 → 锁 Order（直改分支内再锁产品）
    db.execute = AsyncMock(side_effect=[
        MagicMock(scalar_one_or_none=lambda: 5),  # 预读 product_id
        _order(),                                 # 锁单
    ])
    db.add = MagicMock()
    db.flush = AsyncMock()

    user = MagicMock()
    user.is_super = True

    with patch.object(order_commands, 'get_product_for_update',
                      new=AsyncMock(return_value=product)), \
         patch.object(order_commands, '_check_order_lock', new=AsyncMock()), \
         patch.object(order_commands, 'compute_order_status_from_db',
                      new=AsyncMock(return_value='待备货')), \
         patch.object(order_commands, 'cache_mgr',
                      MagicMock(invalidate=AsyncMock(side_effect=_recorder(invalidate_calls)))), \
         patch.object(order_commands, 'schedule_post_commit_invalidation'), \
         patch.object(order_commands, '_safe_invalidate_purchase_cache', new=AsyncMock()), \
         patch.object(order_commands, 'schedule_post_commit_event',
                      side_effect=_recorder(sched_event_calls)), \
         patch.object(order_commands, '_purge_synced_plan_details', new=AsyncMock()), \
         patch.object(order_commands, '_submit_edit_approval') as m_submit, \
         patch.object(order_commands, 'sync_single_item_quantity', new=AsyncMock()), \
         patch.object(order_commands, 'InventoryLog', MagicMock()), \
         patch.object(order_commands, 'dispatch_factory_notifications', new=AsyncMock()):
        await order_commands.update_order(
            db, order_id=1, quantity=200, customer='客', note='注', current_user=user)

    m_submit.assert_not_awaited()  # 超管走直改
    domains = [c[1] for c in invalidate_calls if len(c) > 1]
    assert any(d & CacheDomain.INVENTORY for d in domains), \
        f'update_order 直改分支失效域未覆盖 INVENTORY: {domains}'
    assert sched_event_calls, 'update_order 直改分支未注册 ORDER_UPDATED'
    assert sched_event_calls[0][1] == StockEvent.ORDER_UPDATED
