"""PostgreSQL 快照与版本探测。"""
from __future__ import annotations

import logging
import os

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from .exceptions import DatabaseSnapshotError

logger = logging.getLogger(__name__)


async def get_postgres_snapshot(db: AsyncSession) -> str:
    """获取 PostgreSQL 数据库快照 ID

    使用 pg_export_snapshot() 函数获取一个事务快照 ID，
    用于在备份期间保持数据一致性视图。
    """
    try:
        result = await db.execute(text("SELECT pg_export_snapshot()"))
        snapshot_id = result.scalar()
        if not snapshot_id:
            raise DatabaseSnapshotError("无法获取数据库快照")
        logger.info(f"获取数据库快照成功: {snapshot_id}")
        return snapshot_id
    except SQLAlchemyError as e:
        logger.error(f"获取数据库快照失败: {e}")
        raise DatabaseSnapshotError(f"获取数据库快照失败: {e}") from e


async def get_pg_version(host, port, user, password, env) -> str:
    """获取 PostgreSQL 版本字符串"""
    try:
        from ._proc import run_proc
        from .dump import resolve_pg_tool  # 延迟导入避免与 dump 的循环依赖
        proc = await run_proc(
            [
                resolve_pg_tool('psql'), '-h', host, '-p', port, '-U', user,
                '-d', os.getenv('DB_NAME', 'erp_system'),
                '-t', '-c', 'SELECT version();',
            ],
            env=env, timeout=10,
        )
        if proc.returncode == 0:
            return (proc.stdout or b'').decode(errors='replace').strip().split(',')[0]
    except (TimeoutError, OSError, ValueError) as e:
        logger.warning(f'获取 PG 版本失败: {e}')
    return 'unknown'
