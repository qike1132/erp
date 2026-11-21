"""性能回归（2026-11-21 全量审计，阶段2基准：单查 0.102ms、批量 17.9x）。

批量确认暂存出货此前每行重算结余（2 条全表聚合 SQL）——N 行同产品 ≈ 每行
多 2 条聚合。修复：结余批量预取一次 + 行间按成功确认量递减（自写扣减与
逐行新鲜读语义等价；行失败 savepoint 回滚则不递减）。行为断言（确认成功、
M-13 清理）与 SQL 预算断言双保险；stock_event 侧同批切批量状态版。
"""
from datetime import UTC, date, datetime

from sqlalchemy import event, func, select

from fastapi_app.services.staging import stockout as so_mod
from fastapi_app.shared_models import (
    DailyProductionRecord,
    Order,
    OrderItem,
    Product,
    StagingStockOut,
)

_SID = 'sql-budget-session'


class _SqlCounter:
    def __init__(self, engine):
        self.count = 0
        event.listen(engine.sync_engine, 'before_cursor_execute', self._on_execute)

    def _on_execute(self, *args, **kwargs):
        self.count += 1

    def detach(self, engine):
        event.remove(engine.sync_engine, 'before_cursor_execute', self._on_execute)


async def test_confirm_sql_budget(app_on_test_db, async_db_session):
    """app_on_test_db：编号内核的独立短事务走 require_async_session_local——
    它不会自行重建引擎，先显式 ensure（用重定向后的 URL 在当前 loop 建池）。"""
    from fastapi_app.core.database import ensure_engine_for_current_loop
    await ensure_engine_for_current_loop()
    db = async_db_session
    product = Product(name='SQL预算产品', current_stock=500)
    db.add(product)
    await db.flush()
    # 结余闸门（包装部入库 − 已出货）：预置包装部入库 500
    db.add(DailyProductionRecord(
        department='packaging', product_name='SQL预算产品', barcode='',
        quantity=500, production_date=date(2026, 11, 20), product_id=product.id,
    ))
    # 可出货量基于订单支持：给客户甲备一张 100 件的订单
    order = Order(order_no='SQLBUD-ORD-1', customer='客户甲', quantity=100,
                  order_date=datetime(2026, 11, 20, tzinfo=UTC), status='pending')
    db.add(order)
    await db.flush()
    order.product_id = product.id
    db.add(OrderItem(order_id=order.id, product_id=product.id, quantity=100,
                     product_name='SQL预算产品'))
    # 同产品 2 行（数量不同：同日同客户同产品同数量会被 idem 去重）
    for qty in (3, 5):
        db.add(StagingStockOut(
            session_id=_SID, customer='客户甲', product_name='SQL预算产品',
            product_id=product.id, quantity=qty, status='pending',
            is_validated=True, stock_check_passed=True,
            stockout_date=datetime(2026, 11, 21, tzinfo=UTC),
        ))
    await db.flush()

    counter = _SqlCounter(db.bind)
    try:
        confirmed, errors = await so_mod.confirm_staging_stockouts(db, _SID)
    finally:
        counter.detach(db.bind)

    assert confirmed == 2, errors
    assert errors == []
    # 行间递减正确：同产品第三行（独立会话行）仍能按剩余结余确认
    db.add(StagingStockOut(
        session_id=_SID + '-2', customer='客户甲', product_name='SQL预算产品',
        product_id=product.id, quantity=4, status='pending',  # 数量不同避免 idem 键同日去重
        is_validated=True, stock_check_passed=True,
        stockout_date=datetime(2026, 11, 21, tzinfo=UTC),
    ))
    await db.flush()
    c2, e2 = await so_mod.confirm_staging_stockouts(db, _SID + '-2')
    assert c2 == 1, e2

    # SQL 预算：批量确认 2 行的 SQL 总数有上界（修复前每行多 2 条结余聚合，
    # Red 实测见提交说明）。防止未来回退到逐行聚合。
    assert counter.count <= 60, f'批量确认 2 行 SQL 数 {counter.count} 超预算'

    # M-13：确认后 APPROVED 行应一并清理
    left = (await db.execute(
        select(func.count()).select_from(StagingStockOut).where(
            StagingStockOut.session_id.in_([_SID, _SID + '-2']))
    )).scalar()
    assert left == 0
