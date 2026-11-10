"""库存写路径：stock_changed 必须在事务提交之后发布（回归守卫）。

缺陷背景（2026-11-09）：删除 5000 备货后 /stock 仍显示 5000。数据库已删除
（主库/副本均为 0），但写路径在 commit **之前**发布 stock_changed：
前端收到事件立即重取，读到未提交/副本未回放的旧库存，并按那次读取时间
缓存（staleTime 30s），表现为「删了但页面没变」。

本文件锁死不变量：`schedule_stock_changed` 只登记回调，commit 成功后才发布；
回滚时不得发布。入库/出库/退货/生产入库四条写路径统一走该入口。
"""
from unittest.mock import AsyncMock

import pytest

from fastapi_app.core.exceptions import db_transaction, run_post_commit_callbacks
from fastapi_app.services.notification_service import StockEvent, schedule_stock_changed


@pytest.fixture
def calls():
    return []


def _record(calls, tag):
    def _side_effect(*_args, **_kwargs):
        calls.append(tag)
    return _side_effect


async def test_schedule_stock_changed_defers_until_callbacks_run(mock_db, calls):
    """登记阶段绝不发布；执行 post-commit 回调后才发布。"""
    publish = AsyncMock(side_effect=_record(calls, 'publish'))

    await schedule_stock_changed(
        mock_db, {'product_id': 21396}, context='测试', publish_func=publish,
    )

    assert calls == [], '登记即发布：客户端会在提交前重取到旧库存'
    publish.assert_not_awaited()
    assert mock_db.info.get('post_commit_callbacks'), '事件回调未入队，会被静默丢弃'

    await run_post_commit_callbacks(mock_db)

    assert calls == ['publish']
    publish.assert_awaited_once()
    assert publish.await_args.args[0] == StockEvent.STOCK_CHANGED
    assert publish.await_args.args[1] == {'product_id': 21396}


async def test_db_transaction_publishes_stock_changed_after_commit(mock_db, calls):
    """走 db_transaction 的写路径：commit 成功后才发布事件。"""
    mock_db.commit = AsyncMock(side_effect=_record(calls, 'commit'))
    publish = AsyncMock(side_effect=_record(calls, 'publish'))

    async with db_transaction(mock_db):
        await schedule_stock_changed(
            mock_db, {'product_id': 1}, context='测试', publish_func=publish,
        )
        assert calls == [], '事务体（提交前）内不得发布'

    assert calls == ['commit', 'publish'], f'提交先于发布被破坏: {calls}'


async def test_rollback_discards_stock_changed(mock_db, calls):
    """回滚时不得发布：数据未落库，广播会让客户端重取到旧值。"""
    mock_db.commit = AsyncMock(side_effect=_record(calls, 'commit'))
    publish = AsyncMock(side_effect=_record(calls, 'publish'))

    with pytest.raises(RuntimeError):
        async with db_transaction(mock_db):
            await schedule_stock_changed(
                mock_db, {'product_id': 1}, context='测试', publish_func=publish,
            )
            raise RuntimeError('boom')

    assert calls == [], f'回滚后仍发布了事件: {calls}'
    publish.assert_not_awaited()


async def test_no_info_session_publishes_immediately(calls):
    """测试桩/无 info 会话：退化为立即发布，避免事件在非 UoW 路径丢失。"""
    publish = AsyncMock(side_effect=_record(calls, 'publish'))

    class _NoInfo:
        pass

    await schedule_stock_changed(
        _NoInfo(), {'product_id': 2}, context='测试', publish_func=publish,
    )

    assert calls == ['publish']
    publish.assert_awaited_once()
