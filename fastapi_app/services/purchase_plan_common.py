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
from datetime import UTC, datetime

from sqlalchemy import select
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
    # L1 本地缓存：pp:monthly 和 pp:summary 都用 cache_result 装饰，键形如 `pp:monthly:...`
    invalidate_local_cache('pp:monthly:*')
    invalidate_local_cache('pp:summary:*')

async def _generate_plan_no() -> str:
    """
    生成计划编号：PP-YYYYMMDD-NNNN

    使用独立短事务执行 pg_advisory_xact_lock + SELECT ... FOR UPDATE，
    查询后立即 commit 释放锁，避免在调用方长事务（含 Redis 缓存失效、
    pub/sub 推送等 I/O）期间持锁导致并发请求串行化。

    事务边界策略与 services.numbering.generate_number_async 一致（短事务 + 立即 commit），
    但未引入 asyncio.Lock 进程内串行化与内存计数器补偿层，并发冲突由 plan_no 唯一约束
    + 调用方 _persist_plan_with_retry 的 3 次重试兜底处理。若未来高并发场景冲突频繁，
    可参考 numbering.py 补充 asyncio.Lock + _counters 内存计数器。

    N2 修复：移除未使用的 db 参数。
    """
    from fastapi_app.core.database import _AsyncSessionLocal
    from fastapi_app.core.number_generator import _acquire_advisory_lock_async, _number_lock_key

    today_str = datetime.now(UTC).strftime('%Y%m%d')
    prefix = f'PP-{today_str}-'
    async with _AsyncSessionLocal() as short_session:
        await _acquire_advisory_lock_async(short_session, _number_lock_key('PP', today_str))
        result = await short_session.execute(
            select(PurchasePlan.plan_no)
            .where(PurchasePlan.plan_no.like(f'{prefix}%'))
            .order_by(PurchasePlan.plan_no.desc())
            .limit(1)
            .with_for_update()
        )
        max_no = result.scalar()
        await short_session.commit()  # manual-tx: 独立短会话事务
    if max_no:
        try:
            next_seq = int(max_no.split('-')[-1]) + 1
        except (ValueError, IndexError):
            next_seq = 1
    else:
        next_seq = 1
    return f'{prefix}{next_seq:04d}'


async def _log_action(db: AsyncSession, plan_id: int, action: str, old_value: dict | None, new_value: dict | None, operator: str) -> None:
    """记录操作日志"""
    log = ProductionPlanLog(plan_id=plan_id, action=action, old_value=json.dumps(old_value, ensure_ascii=False) if old_value else None, new_value=json.dumps(new_value, ensure_ascii=False) if new_value else None, operator=operator)
    db.add(log)
    await db.flush()
