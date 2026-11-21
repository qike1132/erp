"""M-13 回归：暂存确认后 APPROVED 行与 REJECTED 行一并清理（2026-11-21 审计）。

此前只清 REJECTED——APPROVED 行每次确认永久留存，三张 staging 表随日常
确认无界增长（全仓无清理任务）。幂等防重由 inventory_log.uq_inventory_log_idem
承担，删行不丢审计。order 域直接测 helper；stockin/stockout 为同一行级改动的
内联块，由既有 staging 套件覆盖执行路径。
"""
from sqlalchemy import func, select

from fastapi_app.core.state_machine import StagingStatus
from fastapi_app.services.staging.order import _purge_rejected_rows
from fastapi_app.shared_models import StagingOrder

_SID = 'purge-test-session'


async def test_purge_removes_both_resolved_statuses(app_on_test_db, async_db_session):
    db = async_db_session
    db.add(StagingOrder(session_id=_SID, customer='客户甲', product_name='产品P',
                        quantity=5, status=StagingStatus.APPROVED))
    db.add(StagingOrder(session_id=_SID, customer='客户甲', product_name='产品P',
                        quantity=6, status=StagingStatus.REJECTED))
    db.add(StagingOrder(session_id=_SID, customer='客户甲', product_name='产品P',
                        quantity=7, status=StagingStatus.PENDING))
    await db.flush()

    await _purge_rejected_rows(db, _SID)

    left = (await db.execute(
        select(func.count()).select_from(StagingOrder)
        .where(StagingOrder.session_id == _SID)
    )).scalar()
    assert left == 1, '只剩未了结的 PENDING 行（修复前 APPROVED 永留 → 2）'
