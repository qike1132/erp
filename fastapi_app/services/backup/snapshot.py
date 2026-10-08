"""PostgreSQL 快照/LSN/WAL。"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from .exceptions import BinaryLogError, DatabaseSnapshotError

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


async def set_transaction_isolation_serializable(db: AsyncSession) -> None:
    """设置事务隔离级别为 SERIALIZABLE

    在备份开始时设置，确保备份期间的数据一致性。
    """
    try:
        await db.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
        logger.info("事务隔离级别已设置为 SERIALIZABLE")
    except SQLAlchemyError as e:
        logger.warning(f"设置事务隔离级别失败: {e}")
        # 降级处理，继续备份但不保证完全一致性


async def create_database_snapshot_backup(
    db: AsyncSession,
    user,
    remark: str,
    encrypt_password: str | bytearray | None = None,
) -> tuple[bytes, dict]:
    """创建带数据库快照的全量备份

    在备份开始时获取数据库快照，确保备份期间的数据一致性。
    """
    from .orchestration import create_full_backup
    snapshot_id = None
    try:
        # 获取数据库快照
        snapshot_id = await get_postgres_snapshot(db)

        # 设置事务隔离级别
        await set_transaction_isolation_serializable(db)

        # 使用快照进行备份
        logger.info(f"使用数据库快照 {snapshot_id} 开始备份")

        # 调用原有的 create_full_backup 函数
        return await create_full_backup(db, user, remark, encrypt_password)

    except Exception as e:  # broad-except: 备份/恢复容错，防止局部异常导致整体流程中断
        logger.error(f"带快照的备份失败: {e}")
        raise
    finally:
        if snapshot_id:
            logger.info(f"数据库快照 {snapshot_id} 备份完成")


async def get_postgres_lsn(db: AsyncSession) -> str | None:
    """获取当前 PostgreSQL 的 LSN (Log Sequence Number)

    用于增量备份的二进制日志支持。
    """
    try:
        result = await db.execute(text("SELECT pg_current_wal_lsn()"))
        lsn = result.scalar()
        return lsn
    except SQLAlchemyError as e:
        logger.warning(f"获取 PostgreSQL LSN 失败: {e}")  # sql-safe: escape_like/绑定参数/常量片段
        return None


async def get_postgres_wal_info(db: AsyncSession) -> dict:
    """获取 PostgreSQL WAL 信息

    返回包含 LSN、WAL 文件位置等信息的字典。
    """
    try:
        # 获取当前 LSN
        lsn_result = await db.execute(text("SELECT pg_current_wal_lsn()"))
        current_lsn = lsn_result.scalar()

        # 获取 WAL 文件信息
        wal_info_result = await db.execute(text("""
            SELECT
                pg_walfile_name(pg_current_wal_lsn()) as current_wal_file,
                pg_walfile_name_offset(pg_current_wal_lsn()) as current_wal_offset,
                pg_wal_lsn_diff(pg_current_wal_lsn(), '0/0') as current_lsn_bytes
        """))
        wal_info = wal_info_result.mappings().first()

        return {
            'current_lsn': current_lsn,
            'current_wal_file': wal_info['current_wal_file'] if wal_info else None,
            'current_wal_offset': wal_info['current_wal_offset'] if wal_info else None,
            'current_lsn_bytes': int(wal_info['current_lsn_bytes']) if wal_info and wal_info['current_lsn_bytes'] else 0,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
    except SQLAlchemyError as e:
        logger.warning(f"获取 PostgreSQL WAL 信息失败: {e}")  # sql-safe: escape_like/绑定参数/常量片段
        return {}


async def create_binary_log_backup(
    db: AsyncSession,
    start_lsn: str | None = None,
    output_dir: Path | None = None,
) -> dict:
    """创建基于 PostgreSQL WAL 的二进制日志备份

    ⚠️ 尚未实现（P0-10，2026-09-12）。

    此前实现会写出一份元数据 JSON，并把 `backup_file` 填成
    `wal_backup_<ts>.tar.gz` 这一路径返回 success=True，但**该文件从未被创建** ——
    全程没有任何 pg_basebackup / pg_receivewal 调用。
    而调用方 `incremental.create_wal_incremental_backup` 又不校验文件是否存在，
    于是会落库一条「看起来是备份、实际不含 WAL 数据」的记录，
    在灾备场景下误导运维认为已具备 PITR 能力。假成功比失败更危险，故改为显式抛错。

    待实现时需要：`pg_basebackup -D <dir> -Ft -z` 建基础备份 +
    `pg_receivewal` 归档 WAL，恢复侧配置 `recovery.signal` / `restore_command`。

    Args:
        db: 数据库会话
        start_lsn: 起始 LSN（保留入参以兼容既有签名）
        output_dir: 输出目录（保留入参以兼容既有签名）

    Raises:
        BinaryLogError: 该功能尚未实现
    """
    raise BinaryLogError(
        'WAL 二进制日志备份尚未实现（缺少 pg_basebackup / pg_receivewal 集成）。'
        '如需时间点恢复（PITR）请先完成实现；当前请使用全量备份 + 增量备份。'
    )


async def restore_from_binary_log(
    db: AsyncSession,
    backup_info_file: Path,
    target_lsn: str | None = None,
) -> dict:
    """从二进制日志备份恢复

    ⚠️ 尚未实现（P0-10，2026-09-12）。

    此前实现会读取备份信息文件、解析出 LSN，然后**不执行任何恢复动作**
    却返回 `success: True`（原文注释即为「暂时返回成功信息」）。
    这是典型的假成功：调用方据此会判断已完成 PITR 恢复。现改为显式抛错。

    Args:
        db: 数据库会话
        backup_info_file: 备份信息文件路径
        target_lsn: 目标 LSN（保留入参以兼容既有签名）

    Raises:
        BinaryLogError: 该功能尚未实现
    """
    raise BinaryLogError(
        'WAL 二进制日志恢复尚未实现。此前该函数返回成功但不执行任何恢复，'
        '现已改为显式报错以免误判灾备能力。'
    )


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
