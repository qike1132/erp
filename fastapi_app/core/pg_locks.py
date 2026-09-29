"""PostgreSQL advisory lock 工具（编号与业务锁共用）。

自 core/number_generator.py 迁出：该模块删除后，CASE 创建锁等业务用途
仍需要同一把事务级 advisory lock。md5 取键方案保持不变，lock key 与
迁移前逐位一致，无运行时行为变更。
"""
import hashlib
import logging

from sqlalchemy import func, select

logger = logging.getLogger(__name__)


def number_lock_key(scope: str, key: str) -> int:
    """为 (scope, key) 生成 64 位 PostgreSQL advisory lock key。"""
    raw = f"{scope}:{key}".encode()
    hex_key = hashlib.md5(raw, usedforsecurity=False).hexdigest()[:15]
    return int(hex_key, 16)


async def acquire_advisory_lock_async(db, lock_key: int) -> None:
    """获取 PostgreSQL 事务级 advisory lock；非 PG 环境则忽略。"""
    try:
        await db.execute(select(func.pg_advisory_xact_lock(lock_key)))
    except Exception:  # defensive: 非PG或测试环境可降级为无advisory lock
        logger.debug("advisory lock 获取失败，降级为无锁模式", exc_info=True)
