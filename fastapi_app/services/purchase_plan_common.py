"""
采购计划基础辅助工具（被多个子模块共享，避免循环依赖）

职责：
    - 事务提交后回调注册（_schedule_post_commit）
    - 采购计划相关缓存失效（_invalidate_plan_caches）
    - 计划编号生成（_generate_plan_no）
    - 操作日志记录（_log_action）

从 purchase_plan_crud.py 拆分而来，保持函数签名不变。
"""
import json
import logging
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.cache import invalidate_local_cache
from fastapi_app.core.cache_invalidation import InvalidationStrategy, cache_mgr
from fastapi_app.services.fifo_allocation import _invalidate_fifo_cache
from fastapi_app.shared_models import ProductionPlanLog, PurchasePlan

# 与原 purchase_plan_crud 模块共享同一 logger 实例，保持日志行为不变
logger = logging.getLogger('fastapi_app.services.purchase_plan_crud')


def _schedule_post_commit(db: AsyncSession, callback: Callable[[], Awaitable[None]]) -> None:
    """注册事务提交成功后执行的异步回调。

    回调会在 db_transaction 上下文管理器成功 commit 后按注册顺序执行；
    若事务回滚则不会执行，避免缓存失效/事件发布发生在持久化失败时。
    """
    callbacks = db.info.setdefault('post_commit_callbacks', [])
    callbacks.append(callback)


async def _invalidate_plan_caches(plan_month: str = '') -> None:
    """清除采购计划相关所有缓存（FIFO + 月度日历 + 客户汇总）

    S4 修复：除了失效 Redis L2 缓存，还显式失效进程内 L1 本地缓存。
    多 worker 部署时 local_ttl 窗口内可能读到陈旧数据，此处统一清除。

    S2 修复：L1 失效模式收窄为精确键 + 前缀通配，避免 `*2026-07*` 误伤无关缓存。
        - FIFO 缓存键固定为 `plan_fifo:YYYY-MM`，用精确匹配。
        - monthly/summary 缓存键以 `pp:monthly:` / `pp:summary:` 为前缀，用前缀通配。
    """
    if plan_month:
        await _invalidate_fifo_cache(plan_month)
        # L1 本地缓存：FIFO 键为 `plan_fifo:YYYY-MM`，精确匹配避免误清
        invalidate_local_cache(f'plan_fifo:{plan_month}')
    await cache_mgr.invalidate(InvalidationStrategy.PATTERN, 'pp:monthly:*')
    await cache_mgr.invalidate(InvalidationStrategy.PATTERN, 'pp:summary:*')
    await cache_mgr.invalidate(InvalidationStrategy.PATTERN, 'pp:agg:*')
    await cache_mgr.invalidate(InvalidationStrategy.PATTERN, 'pp:day:*')
    # L1 本地缓存：pp:monthly/pp:summary/pp:agg/pp:day 都用 cache_result 装饰，键形如 `pp:monthly:...`
    invalidate_local_cache('pp:monthly:*')
    invalidate_local_cache('pp:summary:*')
    invalidate_local_cache('pp:agg:*')
    invalidate_local_cache('pp:day:*')

async def _generate_plan_no() -> str:
    """
    生成计划编号：PP-YYYYMMDD-NNNN

    序号经 numbering_counter 表原子 upsert 分配（见 services.numbering.
    allocate_sequence）：计数独立短事务提交，多 worker 下无重号，业务回滚
    仅产生跳号。种子由 read_daily_max 按编号日期段数值读取（spec §4.4 收口），
    与日期列的时区口径解耦；plan_no 唯一约束与调用方 _persist_plan_with_retry
    的重试保留作为二道防线。
    """
    from fastapi_app.core.database import require_async_session_local
    from fastapi_app.services.numbering import allocate_sequence, read_daily_max
    from fastapi_app.services.numbering_sequence import business_date_str

    today_str = business_date_str()  # 编号日期段北京口径（spec §4.1 统一）
    session_factory = require_async_session_local()
    async with session_factory() as seed_session:
        seed = await read_daily_max(seed_session, PurchasePlan, 'plan_no', today_str)
    next_seq = await allocate_sequence('PP', today_str, seed=seed)
    return f'PP-{today_str}-{next_seq:04d}'


async def _log_action(db: AsyncSession, plan_id: int, action: str, old_value: dict | None, new_value: dict | None, operator: str) -> None:
    """记录操作日志"""
    log = ProductionPlanLog(plan_id=plan_id, action=action, old_value=json.dumps(old_value, ensure_ascii=False) if old_value else None, new_value=json.dumps(new_value, ensure_ascii=False) if new_value else None, operator=operator)
    db.add(log)
    await db.flush()
