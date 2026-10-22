"""M2：采购单撤销的订单状态计算必须批量聚合，不能逐单 N+1。"""
import pytest
from sqlalchemy import event

from fastapi_app.services.order_utils import compute_order_statuses_batch
from fastapi_app.shared_models import Order


@pytest.mark.asyncio
async def test_batch_uses_constant_queries(async_db_session, test_engine):
    db = async_db_session
    orders = [
        Order(order_no=f"T-BATCH-{i}", customer="c", quantity=10)
        for i in range(5)
    ]
    db.add_all(orders)
    await db.flush()

    statements = []

    def _count(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(test_engine.sync_engine, "before_cursor_execute", _count)
    try:
        result = await compute_order_statuses_batch(db, orders)
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", _count)

    assert len(result) == len(orders)
    selects = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
    assert len(selects) <= 2, f"批量状态计算发起了 {len(selects)} 条 SELECT：{selects}"
