"""备份/还原互斥的 HTTP 语义映射（actions 与 restore 异步端点共用）。

背景（2026-09-08 误报事故）：is_restore_in_progress 是 fail-closed 语义——
Redis 认证失败/不可用时也返回 True，旧实现把它直接当成"还原任务执行中"
抛 409，导致 Redis 故障被误报为"已有还原任务正在执行中"。

本模块职责（SRP）：把服务层锁探测结果统一映射为 HTTP 响应——
- Redis 不可用           → 503 LOCK_SERVICE_UNAVAILABLE（不冒充 409）
- 锁持有者已终态（崩溃残留的陈旧锁） → 自愈清除后放行
- 锁被真实持有           → 409 TASK_RUNNING（附带持有者与剩余 TTL 供前端展示）
"""
import logging

from fastapi import HTTPException, status

logger = logging.getLogger(__name__)


async def ensure_restore_slot_free() -> None:
    """确认当前没有真实占用中的还原任务；否则抛 503/409，空闲则直接返回。"""
    from fastapi_app.core.backup_progress import is_redis_available
    from fastapi_app.services import backup as backup_service

    if not await backup_service.is_restore_in_progress():
        return

    # fail-closed 语义下的 True 可能只是 Redis 故障的保守值，先探活区分
    if not await is_redis_available():
        logger.warning('还原锁探测为占用但 Redis 不可用（fail-closed），按锁服务故障返回 503')
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                'code': 'LOCK_SERVICE_UNAVAILABLE',
                'message': '备份锁服务（Redis）暂时不可用，无法确认任务状态，请检查 Redis 后重试',
            },
        )

    # Redis 可用 → 锁确实存在。校验持有者是否已终态（进程崩溃导致的陈旧锁）
    info = await backup_service.get_restore_lock_info()
    holder = (info or {}).get('holder') or 'unknown'
    ttl_seconds = int((info or {}).get('ttl_seconds') or 0)
    if await backup_service.is_stale_restore_lock(holder):
        await backup_service.clear_stale_restore_lock(holder)
        # 清除后复核：期间可能已有新任务真实取得锁，那种情况按真实占用 409
        if not await backup_service.is_restore_in_progress():
            logger.info(f'陈旧还原锁已自愈清除（holder={holder}），放行本次请求')
            return

    minutes = max(1, round(ttl_seconds / 60))
    logger.warning(f'还原锁被真实占用（holder={holder}, ttl={ttl_seconds}s），返回 409')
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            'code': 'TASK_RUNNING',
            'message': f'已有还原任务正在执行中（{holder}，约 {minutes} 分钟后自动释放），请稍后重试',
            'holder': holder,
            'ttl_seconds': ttl_seconds,
        },
    )
