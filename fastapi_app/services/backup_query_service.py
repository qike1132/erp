"""备份查询服务 — 承接 backup 端点包内直写的 SQL

从 endpoints/backup 包下沉的查询与锁操作（纯查询搬移，逻辑零改动）：
- 备份表行数统计（list_backup_tables 聚合）
- BackupRecord 分页列表 / 近30天成功率统计 / 类型分布聚合
- 恢复操作 PostgreSQL advisory lock 获取与释放
- 数据库连通性探测（SELECT 1）

所有函数均接收调用方传入的同一 AsyncSession（除连通性探测自建会话外），
事务边界保持在端点请求事务内，不自行 commit/rollback。
"""
import logging

from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.services.backup_service import RESTORE_LOCK_ID, quote_table
from fastapi_app.shared_models import Base
from fastapi_app.shared_models.backup_record import BackupRecord

logger = logging.getLogger(__name__)


async def get_backup_table_info(db: AsyncSession) -> list[dict]:
    """列出所有可备份的数据库表及行数（白名单校验，单表失败降级为 -1）"""
    # 白名单验证：仅允许 ORM 模型中已定义的表名
    valid_table_names = {t.name for t in Base.metadata.sorted_tables}
    table_info = []
    for table in Base.metadata.sorted_tables:
        name = str(table.name)
        if name not in valid_table_names:
            logger.warning(f'跳过非法表名: {name}')
            continue
        try:
            qtname = quote_table(name)
            result = await db.execute(text(f'SELECT COUNT(*) FROM {qtname}'))  # nosec B608 — qtname 经 quote_table 白名单校验
            count = result.scalar()
        except (SQLAlchemyError, OperationalError, OSError) as e:
            await db.rollback()
            logger.warning(f'统计表 {name} 行数失败: {e}')
            count = -1
        table_info.append({'name': name, 'rows': count})
    return table_info


async def get_backup_records_page(
    db: AsyncSession, page: int, page_size: int,
) -> tuple[list[BackupRecord], int]:
    """备份记录分页查询（按创建时间倒序），返回 (记录列表, 总数)"""
    total_result = await db.execute(select(func.count(BackupRecord.id)))
    total = total_result.scalar() or 0

    offset = (page - 1) * page_size
    stmt = select(BackupRecord).order_by(BackupRecord.created_at.desc()).offset(offset).limit(page_size)
    result = await db.execute(stmt)
    return list(result.scalars().all()), total


async def try_acquire_restore_lock(db: AsyncSession) -> bool:
    """尝试获取恢复操作 PostgreSQL advisory lock（非阻塞），成功返回 True"""
    lock_result = await db.execute(
        text('SELECT pg_try_advisory_lock(:lock_id)'), {'lock_id': RESTORE_LOCK_ID}
    )
    return bool(lock_result.scalar())


async def release_restore_lock(db: AsyncSession) -> None:
    """释放恢复操作 PostgreSQL advisory lock（失败仅记录警告，不抛出）"""
    try:
        await db.execute(
            text('SELECT pg_advisory_unlock(:lock_id)'), {'lock_id': RESTORE_LOCK_ID}
        )
    except Exception:
        logger.warning('释放恢复锁失败')


async def check_database_alive() -> bool:
    """数据库连通性探测（SELECT 1，自建短生命周期会话）"""
    from fastapi_app.core.database import get_async_db_context

    async with get_async_db_context() as db:
        # 执行简单查询
        result = await db.execute(text('SELECT 1'))
        return result.scalar() == 1


async def get_backup_record_stats_since(db: AsyncSession, since) -> tuple[int, int]:
    """统计指定时间以来的备份记录总数与成功数，返回 (总数, 成功数)"""
    stmt = select(
        func.count(BackupRecord.id).label('total'),
        func.sum(func.case((BackupRecord.status == 'success', 1), else_=0)).label('success')
    ).where(BackupRecord.created_at >= since)

    result = await db.execute(stmt)
    stats = result.first()
    return stats.total or 0, stats.success or 0


async def get_backup_type_distribution_since(db: AsyncSession, since) -> dict[str, int]:
    """统计指定时间以来的备份类型分布（type → 数量）"""
    stmt_dist = select(
        BackupRecord.type,
        func.count(BackupRecord.id).label('count')
    ).where(BackupRecord.created_at >= since).group_by(BackupRecord.type)

    result_dist = await db.execute(stmt_dist)
    return {row.type: row.count for row in result_dist}
