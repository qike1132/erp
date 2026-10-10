"""订单写路径：实时事件必须在事务提交之后发布（回归守卫）

缺陷背景（2026-09-30）：在客户订单页删除订单或修改数量后，贝莱订单页（/beile-order）
与外包订单页（/outsource）要等约 30 秒才更新，采购页正常。

根因：写路径把实时事件发在 commit **之前**——
  - `create_order` / `_update_order_directly` 在服务层内 `await _safe_publish_event(...)`，
    此时端点 `db_transaction` 尚未提交；
  - `_delete_order_directly` 在 `flush()` 之后立即调度 ORDER_DELETED 广播，而删除端点
    用的是请求级事务（`get_async_db`）——FastAPI 0.106+ 下其 commit 发生在**响应发送之后**
    （见 core/database.py 的注释）。

客户端收到事件会立刻重取列表，此时读到的是**尚未提交**的旧数据（订单还在 / 数量未变），
并以前端那次读取的时间戳作为 dataUpdatedAt 缓存下来；`staleTime: 30_000` 内不再回取，
于是表现为「删除/改数量后关联页面延迟约 30 秒才更新」。

本文件锁死不变量：**实时事件发布发生在 commit 之后**。
对照的正确写法见 `api/v1/endpoints/approval.py` 与 `services/auxiliary_service.py`
（都是先提交、后发事件）。
"""
from unittest.mock import AsyncMock, patch

import pytest

from fastapi_app.core.exceptions import db_transaction, run_post_commit_callbacks
from fastapi_app.services.notification_service import StockEvent
from fastapi_app.services.order._common import schedule_post_commit_event


@pytest.fixture
def calls():
    """按发生顺序记录 'commit' / 'publish'，用于断言时序"""
    return []


def _record(calls, tag):
    def _side_effect(*_args, **_kwargs):
        calls.append(tag)
    return _side_effect


async def test_scheduled_event_is_not_published_until_callbacks_run(mock_db, calls):
    """注册阶段绝不发布；显式执行回调后才发布"""
    publish = AsyncMock(side_effect=_record(calls, 'publish'))
    with patch('fastapi_app.services.order._common._safe_publish_event', new=publish):
        schedule_post_commit_event(mock_db, StockEvent.ORDER_DELETED, {'order_id': 7})

        assert calls == [], '注册即发布：客户端会在提交前重取到旧数据'
        publish.assert_not_awaited()
        assert mock_db.info.get('post_commit_callbacks'), '事件回调未入队，会被静默丢弃'

        await run_post_commit_callbacks(mock_db)

        assert calls == ['publish']
        publish.assert_awaited_once()
        assert publish.await_args.args[0] == StockEvent.ORDER_DELETED
        assert publish.await_args.args[1] == {'order_id': 7}


async def test_db_transaction_publishes_after_commit(mock_db, calls):
    """走 db_transaction 的写路径：commit 成功后才发布事件"""
    mock_db.commit = AsyncMock(side_effect=_record(calls, 'commit'))
    publish = AsyncMock(side_effect=_record(calls, 'publish'))

    with patch('fastapi_app.services.order._common._safe_publish_event', new=publish):
        async with db_transaction(mock_db):
            schedule_post_commit_event(mock_db, StockEvent.ORDER_UPDATED, {'order_id': 9})
            assert calls == [], '事务体（提交前）内不得发布'

        assert calls == ['commit', 'publish'], f'提交先于发布被破坏: {calls}'


async def test_rollback_discards_scheduled_event(mock_db, calls):
    """事务回滚时不得发布事件（数据未落库，广播出去会让客户端重取到旧数据）"""
    mock_db.commit = AsyncMock(side_effect=_record(calls, 'commit'))
    publish = AsyncMock(side_effect=_record(calls, 'publish'))

    with patch('fastapi_app.services.order._common._safe_publish_event', new=publish):
        with pytest.raises(RuntimeError):
            async with db_transaction(mock_db):
                schedule_post_commit_event(mock_db, StockEvent.ORDER_UPDATED, {'order_id': 9})
                raise RuntimeError('boom')

    assert calls == [], f'回滚后仍发布了事件: {calls}'
    publish.assert_not_awaited()


async def test_run_post_commit_callbacks_tolerates_no_info_session():
    """回归（B2）：无 info 属性的会话（测试桩、轻量包装）不得让 get_async_db 收尾崩溃。

    schedule 侧（cache_invalidation/domain_events）对无 info 会话已做退化容错，
    执行侧此前仍硬取 session.info —— database.get_async_db 提交成功后调用本函数时
    AttributeError 会冒泡成 500。口径对齐：无 info 即无注册入口，静默跳过。
    """
    class _NoInfoSession:
        pass

    # 不抛异常即通过
    await run_post_commit_callbacks(_NoInfoSession())


async def test_delete_endpoint_commits_before_broadcasting(client, mock_db, calls):
    """删除端点：必须先在请求内提交（响应返回即已落库），再广播 ORDER_DELETED

    这里用「按服务层真实契约注册 post-commit 事件」的替身，专门钉住端点侧责任：
    端点若不自行 commit + 执行回调，事件就不会广播（实时刷新失效），
    或者会早于提交广播（客户端重取到旧数据）。
    """
    mock_db.commit = AsyncMock(side_effect=_record(calls, 'commit'))
    publish = AsyncMock(side_effect=_record(calls, 'publish'))

    async def _fake_delete_order(db, order_id, user):
        # 与 services/order/commands._delete_order_directly 一致：注册「提交后广播」
        schedule_post_commit_event(db, StockEvent.ORDER_DELETED, {'order_id': order_id})
        return {'success': True, 'message': '订单删除成功！'}

    with patch(
        'fastapi_app.api.v1.endpoints.order.order_service.delete_order',
        new=AsyncMock(side_effect=_fake_delete_order),
    ), patch(
        'fastapi_app.services.order._common._safe_publish_event', new=publish,
    ), patch(
        'fastapi_app.api.v1.endpoints.order.publish_domain_event', new=AsyncMock(),
    ):
        response = await client.delete('/api/v1/orders/delete/1')

    assert response.status_code == 200
    assert 'commit' in calls, '删除未在请求内提交：客户端可能在提交前重取到旧数据'
    assert 'publish' in calls, 'ORDER_DELETED 未广播：关联页面只能等 staleTime 过期'
    assert calls.index('commit') < calls.index('publish'), f'广播早于提交: {calls}'
