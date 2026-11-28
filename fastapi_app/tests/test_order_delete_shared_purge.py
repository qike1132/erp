"""订单删除的关联行清理必须收敛到共享实现 _purge_order_related_rows（审计 M-01 回归）。"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi_app.services.order import commands


class _EmptyResult:
    def scalars(self):
        return self

    def all(self):
        return []


async def test_shared_purge_cleans_expected_tables():
    """行为级守卫：共享 purge 的 DELETE 表集合固定。"""
    captured: list[str] = []

    async def fake_execute(stmt, *_args, **_kwargs):
        captured.append(str(stmt))
        return _EmptyResult()

    db = AsyncMock()
    db.execute = fake_execute
    order = SimpleNamespace(id=42, order_no='PO-42', product_id=None)
    graph = {'process_ids': []}

    with patch.object(
        commands, 'detach_cancelled_returns_for_order', new=AsyncMock(),
    ), patch(
        'fastapi_app.services.shipment_plan_sync.purge_shipment_plan_details_for_order',
        new=AsyncMock(return_value={'detail_deleted': 0}),
    ):
        await commands._purge_order_related_rows(
            db, order, order.id, graph,
        )

    sql = ' '.join(captured).lower()
    for table in (
        'stock_out', 'order_sync_record', 'sync_retry_queue',
        'order_status_log', 'order_item',
    ):
        assert f'delete from {table}' in sql, f'缺少清理表: {table}'
