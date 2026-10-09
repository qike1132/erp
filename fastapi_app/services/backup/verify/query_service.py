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
import re
from datetime import UTC, datetime

from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.services.backup._constants import RESTORE_LOCK_ID
from fastapi_app.services.backup.verify.core import quote_table
from fastapi_app.shared_models import Base
from fastapi_app.shared_models.backup_record import BackupRecord

logger = logging.getLogger(__name__)

# 文件名时间戳解析正则：erp_*_YYYYMMDD_HHMMSS[mmm].{zip,json}[.enc]
# 毫秒段可选（3 位纯数字、无点，对齐 cleanup/service.py 的 18 位口径）：
# 第十四轮为解决同秒双全量同名互覆，文件名加了 3 位毫秒后缀；
# 锚定 $ 之前不容-optional 会让这些新备份解析不出 created_at（补录与排序的唯一兜底）。
# 注意：加密备份是双重后缀 `.zip.enc`，后缀必须是 (?:zip|json)(?:\.enc)? —— 只枚举
# `enc` 会因「.zip.」段落在 `\.enc` 之前而整体匹配失败（曾致 .zip.enc 恒解析不出时间）。
_FILENAME_TIMESTAMP_RE = re.compile(r'_(\d{8})_(\d{6})(?:\d{3})?\.(?:zip|json)(?:\.enc)?$')


def _parse_exported_at(value: str | None) -> datetime | None:
    """将 'YYYY-MM-DD HH:MM:SS' 格式字符串解析为 datetime，失败返回 None"""
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
    except (ValueError, TypeError):
        return None


def _parse_timestamp_from_filename(filename: str) -> datetime | None:
    """从文件名提取时间戳（格式 erp_*_YYYYMMDD_HHMMSS[.mmm].zip），失败返回 None"""
    if not filename:
        return None
    m = _FILENAME_TIMESTAMP_RE.search(filename)
    if not m:
        return None
    try:
        return datetime.strptime(f'{m.group(1)}{m.group(2)}', '%Y%m%d%H%M%S')
    except (ValueError, TypeError):
        return None


def _infer_type_from_filename(filename: str) -> str:
    """从文件名推断备份类型：erp_incremental_→incremental，erp_auto_/erp_backup_→full"""
    if not filename:
        return 'full'
    if filename.startswith('erp_incremental_'):
        return 'incremental'
    return 'full'


def _infer_trigger_type_from_filename(filename: str) -> str:
    """从文件名推断触发方式：erp_auto_→auto，其他→manual"""
    if not filename:
        return 'manual'
    if filename.startswith('erp_auto_'):
        return 'auto'
    return 'manual'


def _resolve_created_at(fs_entry: dict, filename: str) -> datetime | None:
    """解析记录创建时间：优先 exported_at，其次文件名时间戳"""
    created_at = _parse_exported_at(fs_entry.get('exported_at'))
    if created_at is not None:
        return created_at
    return _parse_timestamp_from_filename(filename)


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
            result = await db.execute(text(f'SELECT COUNT(*) FROM {qtname}'))  # nosec B608 — qtname 经 quote_table 白名单校验; batch-loop: 逐表备份/恢复,无法批量
            count = result.scalar()
        except (SQLAlchemyError, OperationalError, OSError) as e:
            await db.rollback()  # manual-tx: try/except 内显式事务控制
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


# 名称刻意区别于 Redis 版 release_restore_lock（services/backup/restore.py）：同名会经 .verify 星号导入遮蔽包级导出
async def release_advisory_restore_lock(db: AsyncSession) -> None:
    """释放恢复操作 PostgreSQL advisory lock（失败仅记录警告，不抛出）"""
    try:
        await db.execute(
            text('SELECT pg_advisory_unlock(:lock_id)'), {'lock_id': RESTORE_LOCK_ID}
        )
    except Exception:  # broad-except: 备份/恢复容错，防止局部异常导致整体流程中断
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
    # Row.count 与 tuple.count 同名，静态上被解析为方法；列值须经 RowMapping 取（运行时为同一 int）
    return {row.type: row._mapping['count'] for row in result_dist}


async def get_merged_backup_records(
    db: AsyncSession, page: int, page_size: int,
) -> tuple[list[dict], int]:
    """合并查询备份记录：以文件系统扫描为基准，左连接数据库记录。

    返回 (记录列表, 总数)。每条记录包含 source 字段标记来源：
    - source='db'：文件系统存在且数据库有匹配记录，合并数据库专属字段
    - source='fs'：文件系统存在但数据库无匹配记录，从文件系统信息构建

    排序：按 created_at 倒序；分页：page 从1开始。
    """
    # 1) 扫描文件系统所有备份文件（list_backup_files 已按文件名倒序排序）
    # 延迟导入避免循环依赖：backup.__init__ → incremental → json_backup → verify → query_service
    from fastapi_app.services.backup import list_backup_files

    fs_entries = list_backup_files()
    filenames = [e.get('filename') for e in fs_entries if e.get('filename')]

    # 2) 批量查询数据库匹配记录，构建 filename → BackupRecord 映射（避免 N+1）
    db_map: dict[str, BackupRecord] = {}
    if filenames:
        stmt = select(BackupRecord).where(BackupRecord.filename.in_(filenames))
        result = await db.execute(stmt)
        for rec in result.scalars().all():
            if rec.filename:
                db_map[rec.filename] = rec

    # 3) 以文件系统列表为基准合并记录
    merged: list[dict] = []
    for fs_entry in fs_entries:
        filename = fs_entry.get('filename') or ''
        db_rec = db_map.get(filename)

        if db_rec is not None:
            # 数据库有匹配记录：合并数据库专属字段
            merged.append({
                'id': db_rec.id,
                'type': db_rec.type,
                'trigger_type': db_rec.trigger_type,
                'filename': db_rec.filename or filename,
                'size': db_rec.size if db_rec.size is not None else fs_entry.get('size'),
                'table_count': db_rec.table_count if db_rec.table_count is not None else fs_entry.get('table_count'),
                'total_rows': db_rec.total_rows if db_rec.total_rows is not None else fs_entry.get('total_rows'),
                'operator': db_rec.operator,
                'remark': db_rec.remark or fs_entry.get('remark'),
                'status': db_rec.status,
                'error_message': db_rec.error_message,
                'duration_seconds': db_rec.duration_seconds,
                'ip_address': db_rec.ip_address,
                'user_agent': db_rec.user_agent,
                'parent_record_id': db_rec.parent_record_id,
                'created_at': db_rec.created_at,
                'updated_at': db_rec.updated_at,
                'source': 'db',
                'encrypted': db_rec.encrypted if db_rec.encrypted is not None else fs_entry.get('encrypted'),
            })
        else:
            # 数据库无匹配记录：从文件系统信息构建（文件存在即视为成功）
            created_at = _resolve_created_at(fs_entry, filename)
            merged.append({
                'id': None,
                'type': _infer_type_from_filename(filename),
                'trigger_type': _infer_trigger_type_from_filename(filename),
                'filename': filename,
                'size': fs_entry.get('size'),
                'table_count': fs_entry.get('table_count'),
                'total_rows': fs_entry.get('total_rows'),
                'operator': fs_entry.get('exported_by'),
                'remark': fs_entry.get('remark'),
                'status': 'success',
                'error_message': fs_entry.get('error'),
                'duration_seconds': None,
                'ip_address': None,
                'user_agent': None,
                'parent_record_id': None,
                'created_at': created_at,
                'updated_at': None,
                'source': 'fs',
                'encrypted': fs_entry.get('encrypted'),
            })

    # 4) 按创建时间倒序排序（统一转为 aware datetime，避免 naive/aware 混合比较抛 TypeError）
    def _sort_key(r: dict) -> datetime:
        """排序 key：统一转为 aware datetime，避免 naive/aware 混合比较抛 TypeError"""
        ca = r.get('created_at')
        if ca is None:
            return datetime.min.replace(tzinfo=UTC)
        if isinstance(ca, datetime) and ca.tzinfo is None:
            return ca.replace(tzinfo=UTC)
        return ca

    merged.sort(key=_sort_key, reverse=True)

    # 5) 分页截取
    total = len(merged)
    offset = (page - 1) * page_size
    page_records = merged[offset:offset + page_size]

    return page_records, total
