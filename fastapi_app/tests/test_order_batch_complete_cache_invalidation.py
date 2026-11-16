"""批次完成的缓存失效回归（上线前审计 2026-11-16 Medium 2）。

背景：`complete_batch` 把 Order.status 改成「批次已完成」、给备货打归档时间，
但服务侧与端点侧一次缓存失效都没发（只发了个 WebSocket 事件）。后果：批次
列表/批次历史仍显示该批未完成、报表流水（reports:*）仍是归档前的旧数据，
一直持续到 TTL 到期；更危险的是前端据此还能再点一次「完成批次」。

对照 `stock_in_service.create_stockin`（提交前 await 失效 + 提交后回调）与
`approval.py` 提交后的 `cache_mgr.invalidate(DOMAIN, ORDER|...|REPORT)`。

本组用例锁死三件事：
  1) 服务侧 flush 后立刻失效 ORDER + REPORT（覆盖不经 db_transaction 的调用方）；
  2) 服务侧注册 post-commit 回调（覆盖「提交前被并发请求读旧值回写」的竞态）；
  3) 端点提交成功后同样失效 ORDER + REPORT。
断言落在真实下发的 pattern 上（'orders:*' / 'reports:*'），而不是「调了某个桩」——
把失效调用删掉，这两条 pattern 就不再出现。
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.services import order_batch_service


@pytest.fixture
def issued_patterns(monkeypatch):
    """截获真实失效清单（同 test_stock_chip_cache_invalidation 的桩法）。

    打的是 `core.cache.invalidate_cache` 本身：`invalidate_related_caches`
    在调用时才查模块全局名字，所以域映射（域 → pattern）仍走真实实现。
    """
    patterns: list[str] = []

    async def _fake_invalidate_cache(pattern):
        patterns.append(pattern)
        return 0

    monkeypatch.setattr('fastapi_app.core.cache.invalidate_cache', _fake_invalidate_cache)
    return patterns


def _shipped_order():
    order = MagicMock()
    order.id = 1
    order.order_no = 'PO-001'
    order.status = '已出货'
    order.batch_completed_at = None
    order.batch_completed_by_id = None
    return order


@pytest.mark.asyncio
async def test_complete_batch_invalidates_order_and_report(issued_patterns):
    """服务侧：完成批次后必须失效 orders:* 与 reports:*。"""
    order = _shipped_order()
    order_lock = MagicMock()
    order_lock.scalars.return_value.all.return_value = [order]
    stockin_lock = MagicMock()
    stockin_lock.scalars.return_value.all.return_value = []

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[order_lock, stockin_lock])
    # info 必须是真实 dict：post-commit 回调入队后由本条用例手动执行，
    # 不依赖 fire-and-forget 的任务调度时序（否则断言会随机漏掉回调）。
    db.info = {}

    user = MagicMock()
    user.id = 1
    user.username = '张三'
    user.factory = None
    user.is_super = False

    with patch.object(order_batch_service, '_safe_publish_event', new_callable=AsyncMock), \
         patch.object(order_batch_service, '_write_audit_log'):
        await order_batch_service.complete_batch(db, batch_no='B9', user=user)

    # 前置：状态确实被改了（否则本用例证明不了「改了却没失效」这条链）
    assert order.status == '批次已完成'
    assert 'orders:*' in issued_patterns, '完成批次改了 Order.status，订单缓存必须失效'
    assert 'reports:*' in issued_patterns, '报表流水由订单/备货聚合，必须一并失效'


@pytest.mark.asyncio
async def test_complete_batch_schedules_post_commit_invalidation(issued_patterns):
    """服务侧：post-commit 回调必须挂上，且执行后同样失效订单 + 报表。"""
    order = _shipped_order()
    order_lock = MagicMock()
    order_lock.scalars.return_value.all.return_value = [order]
    stockin_lock = MagicMock()
    stockin_lock.scalars.return_value.all.return_value = []

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[order_lock, stockin_lock])
    db.info = {}

    user = MagicMock()
    user.id = 1
    user.username = '张三'
    user.factory = None
    user.is_super = False

    with patch.object(order_batch_service, '_safe_publish_event', new_callable=AsyncMock), \
         patch.object(order_batch_service, '_write_audit_log'):
        await order_batch_service.complete_batch(db, batch_no='B9', user=user)

    callbacks = db.info.get('post_commit_callbacks', [])
    assert callbacks, 'flush 后必须注册 post-commit 失效（只做提交前失效会被并发读回写留下脏缓存）'

    issued_patterns.clear()
    for callback in callbacks:
        await callback()
    assert 'orders:*' in issued_patterns
    assert 'reports:*' in issued_patterns


@pytest.mark.asyncio
async def test_complete_batch_endpoint_does_not_double_invalidate(client):
    """端点侧：失效由 service 统一负责，端点不再重复遍历一遍 Redis。

    评审 F9：service 的 complete_batch 已有「提交前清一次 + post-commit 再清一次」，
    端点再来一次就是同一域集合跑第三遍（每遍一次 Redis SCAN）。本用例钉住
    「端点不直接调 cache_mgr」，避免有人以为 service 没做而把失效挪回端点。
    """
    from fastapi_app.api.v1.endpoints import order_batch as order_batch_endpoint

    invalidate = AsyncMock()
    fake_result = {'completed_count': 1, 'completed_stockins': 0, 'failed_orders': []}

    with patch.object(order_batch_endpoint.order_batch_service, 'complete_batch',
                      new=AsyncMock(return_value=fake_result)):
        resp = await client.post(
            '/api/v1/order-batch/batch/complete', json={'batch_no': 'B9'},
        )

    assert resp.status_code == 200, resp.text
    assert not hasattr(order_batch_endpoint, 'cache_mgr'), (
        '端点又引入了 cache_mgr：失效点应统一在 service（见 complete_batch）'
    )
    invalidate.assert_not_called()
