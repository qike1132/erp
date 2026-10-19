"""审批删除路径的锁序回归（2026-10-19 OCR 第四轮 H3）。

_handle_delete_approval 原先先锁 Order 行（O）、回滚内部才升序锁 product 行
（P），与 create_stockout_core（先 get_product_for_update 再经
calculate_available_shipment_quantity 锁 Order）、update_order、
_load_order_for_delete 的既定 P→O 锁序互逆——审批删除与出货创建并发时构成
AB-BA 死锁，PG 强杀一方（生产表现为 500/重试）。修复后本路径须先调
order/commands.py::_prelock_order_products（全集升序预锁，回滚内部重锁
全部 no-op）再锁 Order 行。

死锁无法稳定单测（并发互压 flaky），本文件锁**调用顺序**：预锁必须发生在
Order 行锁之前、StockOut 快照读必须在 Order 锁之后（M2 语义不回归）——
把预锁调用变异掉，本文件必红。
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi_app.services import approval_service


async def test_delete_approval_prelocks_products_before_order_lock(mock_db):
    """审批删除锁序 P→O：_prelock_order_products 先于 Order 行锁执行。"""
    calls: list[str] = []

    async def _fake_prelock(db, order_id, *extra_pids):
        calls.append(f'prelock:{order_id}')

    async def _fake_execute(stmt, *args, **kwargs):
        # order 是 SQL 保留字，编译文本呈 FROM "order"（带引号），不能裸匹配
        # 'FROM order'；DELETE FROM stock_out 也不得误判为快照读。
        text = ' '.join(str(stmt).split())
        if text.startswith('SELECT') and 'FROM "order"' in text:
            # Order 行锁：SELECT order.id ... FOR UPDATE；无 FOR UPDATE 的
            # order 读不算锁（防止把普通读误判成锁序证据）
            calls.append('lock_order' if 'FOR UPDATE' in text else 'order_read_no_lock')
        elif text.startswith('SELECT') and 'FROM stock_out' in text:
            calls.append('read_stockouts')
        else:
            calls.append('execute_other')
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        result.all.return_value = []
        return result

    mock_db.execute = AsyncMock(side_effect=_fake_execute)

    order = SimpleNamespace(id=42, order_no='T-LOCK-42', product_id=None)
    # requester_id：函数尾段 order.deleted_by_id = approval.requester_id 会读它
    approval = SimpleNamespace(id=9, order_id=42, requester_id=1)
    current_user = SimpleNamespace(id=1, username='lock-tester')

    with patch(
        'fastapi_app.services.approval_service.assert_no_linked_returns',
        new=AsyncMock(),
    ), patch(
        'fastapi_app.services.approval_service.rollback_order_stock_by_sku',
        new=AsyncMock(return_value=0),
    ), patch(
        'fastapi_app.services.approval_service._backup_and_audit_deleted_order',
        new=AsyncMock(),
    ), patch(
        'fastapi_app.services.approval_service.detach_cancelled_returns_for_order',
        new=AsyncMock(),
    ), patch(
        'fastapi_app.services.shipment_plan_sync.purge_shipment_plan_details_for_order',
        new=AsyncMock(),
    ), patch(
        # _handle_delete_approval 函数体内延迟导入，patch 模块属性即可命中
        'fastapi_app.services.order.commands._prelock_order_products',
        new=_fake_prelock,
    ):
        await approval_service._handle_delete_approval(
            mock_db, approval, order, current_user)

    assert calls[0] == 'prelock:42', (
        f'审批删除必须先预锁产品全集再碰数据库（P→O），实际首个调用：{calls}')
    assert calls[1] == 'lock_order', (
        f'预锁后的第一个 db 操作应是 Order 行锁，实际调用序列：{calls}')
    assert 'read_stockouts' in calls, (
        f'须读到 StockOut 快照供回滚使用，实际调用序列：{calls}')
    assert calls.index('read_stockouts') > calls.index('lock_order'), (
        f'StockOut 快照读必须在 Order 锁之后（M2 语义不回归），实际：{calls}')
