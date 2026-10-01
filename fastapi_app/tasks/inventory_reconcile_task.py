"""库存只读对账 ARQ 任务（P1-1）。

只读：任务只开会话跑一次对账，**不 commit、不写任何业务表**；失败交由 ARQ 按
``max_tries`` 重试（与其他巡检任务一致）。

注册策略：函数始终进 ``WorkerSettings.functions``（运维可手动 ``enqueue_job`` 触发
或排障），但低频 cron **默认不注册** —— 观察期结束、确认聚合开销与报告口径后，把
``INVENTORY_RECONCILE_ENABLED`` 置真，fastapi_app/core/arq_app.py 才会把
:func:`inventory_reconcile_cron_entry` 追加进 ``cron_schedules``。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi_app.core.database import require_async_session_local
from fastapi_app.services.inventory_reconcile import (
    CRON_HOUR,
    CRON_MINUTE,
    reconcile_inventory,
)

logger = logging.getLogger(__name__)

#: cron 条目名（arq worker 日志与 ``cron_schedules`` 中的稳定标识）。
CRON_NAME = 'inventory-reconcile'


async def inventory_reconcile_task(ctx: Any) -> dict[str, Any]:
    """ARQ 入口：只读对账一次并返回差异报告（无写点、无 commit）。"""
    session_factory = require_async_session_local()
    async with session_factory() as db:
        report = await reconcile_inventory(db)
    logger.info(
        '库存只读对账完成: products=%d diffs=%d(正 %d / 负 %d) net=%d 明细=%d 截断=%s',
        report['checked_products'],
        report['diff_count'],
        report['positive_count'],
        report['negative_count'],
        report['net_diff'],
        len(report['diffs']),
        report['truncated'],
    )
    return report


def inventory_reconcile_cron_entry() -> dict[str, Any]:
    """构造 arq ``cron_schedules`` 条目（供 arq_app 在 env 开关打开时追加）。"""
    return {
        'name': CRON_NAME,
        'func': inventory_reconcile_task,
        'cron': {'hour': CRON_HOUR, 'minute': CRON_MINUTE},
        'schedule': f'{CRON_HOUR}:{CRON_MINUTE:02d}',
        'timeout': 300,
    }
