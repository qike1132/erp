"""审批删单必须复用直删的共享清理实现（审计 M-01 回归）。"""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi_app.services.order import commands

SOURCE = Path('fastapi_app/services/approval_service.py').read_text(encoding='utf-8')
START = SOURCE.index('async def _handle_delete_approval')
END = SOURCE.index('_OPERATION_HANDLERS', START)
BODY = SOURCE[START:END]


def test_approval_delete_delegates_to_shared_purge():
    assert '_purge_order_related_rows' in BODY, '审批删单必须调用共享清理函数'
    assert 'keep_approval_id=approval.id' in BODY, '当前审批行必须保留'


def test_approval_delete_no_longer_hand_copies_related_deletes():
    assert 'sa_delete(StockOut' not in BODY, '出库删除应交给共享实现'
    assert 'sa_delete(OrderItem' not in BODY, '订单明细删除应交给共享实现'
    assert 'detach_cancelled_returns_for_order' not in BODY, '退货解绑应交给共享实现'


class _EmptyResult:
    def scalars(self):
        return self

    def all(self):
        return []


async def test_shared_purge_keeps_current_approval_and_cleans_expected_tables():
    """行为级守卫：共享 purge 的 DELETE 表集合固定，且 keep_approval_id 生效。"""
    captured: list[str] = []

    async def fake_execute(stmt, *_args, **_kwargs):
        captured.append(str(stmt))
        return _EmptyResult()

    db = AsyncMock()
    db.execute = fake_execute
    order = SimpleNamespace(id=42, order_no='PO-42', product_id=None)
    graph = {'approval_ids': [9, 10], 'process_ids': []}

    with patch.object(
        commands, 'detach_cancelled_returns_for_order', new=AsyncMock(),
    ), patch(
        'fastapi_app.services.shipment_plan_sync.purge_shipment_plan_details_for_order',
        new=AsyncMock(return_value={'detail_deleted': 0}),
    ):
        await commands._purge_order_related_rows(
            db, order, order.id, graph, keep_approval_id=9,
        )

    sql = ' '.join(captured).lower()
    for table in (
        'stock_out', 'order_sync_record', 'sync_retry_queue',
        'order_status_log', 'order_item', 'approval_log', 'approval_request',
    ):
        assert f'delete from {table}' in sql, f'缺少清理表: {table}'
    assert 'approval_request.id !=' in sql, '当前审批行必须排除在删除之外'
    assert 'approval_log.approval_request_id in' in sql, '其余审批日志应删除'

