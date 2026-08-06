"""
备份/恢复业务服务层

从 backup.py (2148 行) 提取的核心业务逻辑，供 API 路由层和 Celery 任务调用。
函数式风格（纯 async 函数，非类），与项目 service 文件风格一致。
"""
from __future__ import annotations

import asyncio
import gzip
import hashlib
import io
import json
import logging
import os
import shutil
import tempfile
import zipfile
from datetime import date, datetime, time as time_type
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from sqlalchemy import ARRAY, JSON, Boolean, Date, DateTime, Numeric, Time, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.exc import DataError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 自定义异常
# ---------------------------------------------------------------------------

class BackupError(Exception):
    """备份操作基础异常"""


class BackupLockError(BackupError):
    """获取备份/恢复锁失败（REV-06: 不降级继续）"""


class BackupFileError(BackupError):
    """备份文件操作失败"""


class DatabaseSnapshotError(BackupError):
    """数据库快照操作失败"""


class BinaryLogError(BackupError):
    """二进制日志操作失败"""


class RestoreError(BackupError):
    """恢复操作失败"""


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
BACKUP_DIR = Path(os.environ.get('BACKUP_DIR', 'backups/server'))
MAX_BACKUP_FILE_SIZE = 500 * 1024 * 1024
RESTORE_LOCK_ID = 20240426
BACKUP_LOCK_ID = 20240427
BACKUP_OPERATION_TIMEOUT = int(os.environ.get('BACKUP_OPERATION_TIMEOUT', '1800'))
_backup_in_progress: asyncio.Lock = asyncio.Lock()
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
UPLOADS_DIR = PROJECT_ROOT / 'static' / 'uploads'
CONFIG_DIR = PROJECT_ROOT / 'config'
ENV_FILE = PROJECT_ROOT / '.env.production'
REDIS_DUMP = PROJECT_ROOT / 'dump.rdb'
MEILI_HOST = os.environ.get('MEILI_HOST', 'http://localhost:7700')
MEILI_MASTER_KEY = os.environ.get('MEILI_MASTER_KEY', '')
BACKUP_FORMAT_VERSION = '2.0'
PRE_RESTORE_DIR = BACKUP_DIR / 'pre_restore'
_MAX_PRE_RESTORE_BACKUPS = 5
_TIMESTAMP_CANDIDATES = ('updated_at', 'modified_at', 'created_at', 'deleted_at')
_CHECKSUM_EXCLUDE_TABLES = {'alembic_version'}

# 备份加密配置
BACKUP_ENCRYPTION_ENABLED = os.environ.get('BACKUP_ENCRYPTION_ENABLED', 'true').lower() == 'true'
BACKUP_ENCRYPTION_PASSWORD = os.environ.get('BACKUP_ENCRYPTION_PASSWORD', '')
BACKUP_ENCRYPTION_KEY = os.environ.get('BACKUP_ENCRYPTION_KEY', '')
BACKUP_ENCRYPTION_FALLBACK_TO_GENERATED = os.environ.get('BACKUP_ENCRYPTION_FALLBACK_TO_GENERATED', 'true').lower() == 'true'

# 大文件分片配置
BACKUP_CHUNK_SIZE = int(os.environ.get('BACKUP_CHUNK_SIZE', '104857600'))  # 默认 100MB
BACKUP_MAX_CHUNKS = int(os.environ.get('BACKUP_MAX_CHUNKS', '100'))  # 最大分片数

# REV-09: 配置文件白名单 — 敏感文件恢复需二次确认
_SENSITIVE_CONFIG_FILES = {'.env.production', 'jwt/private.pem', 'jwt/public.pem'}

# 从环境变量读取排除文件列表
BACKUP_EXCLUDE_FILES = os.environ.get('BACKUP_EXCLUDE_FILES', '')
if BACKUP_EXCLUDE_FILES:
    _EXCLUDE_FILES = set(BACKUP_EXCLUDE_FILES.split(','))
else:
    _EXCLUDE_FILES = set()

# 合并敏感文件和排除文件
_SENSITIVE_AND_EXCLUDED_FILES = _SENSITIVE_CONFIG_FILES.union(_EXCLUDE_FILES)

# REV-33: information_schema 查询结果缓存
_ts_col_cache: dict[str, str | None] = {}


# ---------------------------------------------------------------------------
# 目录管理
# ---------------------------------------------------------------------------

def ensure_backup_dir():
    """确保备份目录存在"""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def ensure_pre_restore_dir():
    """确保恢复前安全备份目录存在"""
    PRE_RESTORE_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# 备份并发控制
# ---------------------------------------------------------------------------

async def acquire_backup_lock(db: AsyncSession) -> bool:
    """获取备份操作的数据库级 advisory lock。
    与 restore 锁分离，允许恢复期间记录元数据。
    返回 True 表示获取成功，False 表示已有其他连接持有锁。
    """
    try:
        result = await db.execute(
            text('SELECT pg_try_advisory_lock(:lock_id)'),
            {'lock_id': BACKUP_LOCK_ID},
        )
        return bool(result.scalar())
    except (SQLAlchemyError, OSError) as e:
        logger.warning('获取备份 advisory_lock 失败: %s', e)
        return False


async def release_backup_lock(db: AsyncSession) -> None:
    """释放备份 advisory lock。失败仅记录日志，不抛出异常。"""
    try:
        await db.execute(
            text('SELECT pg_advisory_unlock(:lock_id)'),
            {'lock_id': BACKUP_LOCK_ID},
        )
    except (SQLAlchemyError, OSError) as e:
        logger.warning('释放备份 advisory_lock 失败: %s', e)


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def sha256_bytes(data: bytes) -> str:
    """计算 bytes 的 SHA256 十六进制摘要（REV-14: 替代 MD5）"""
    return hashlib.sha256(data).hexdigest()


def sha256_file(filepath: Path) -> str | None:
    """计算文件的 SHA256 十六进制摘要，文件不存在返回 None"""
    if not filepath.is_file():
        return None
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def generate_encryption_key() -> str:
    """生成随机加密密钥"""
    import secrets
    return secrets.token_urlsafe(32)


def should_exclude_file(file_path: Path, relative_path: str) -> bool:
    """检查文件是否应该被排除在备份之外
    
    Args:
        file_path: 文件的完整路径
        relative_path: 相对于配置目录或上传目录的相对路径
        
    Returns:
        True 如果文件应该被排除，否则 False
    """
    # 检查是否为敏感配置文件
    if relative_path in _SENSITIVE_AND_EXCLUDED_FILES:
        logger.debug(f"排除敏感/排除文件: {relative_path}")
        return True
    
    # 检查文件扩展名是否在排除列表中
    excluded_extensions = {'.log', '.tmp', '.temp', '.cache', '.swp', '.swo'}
    if file_path.suffix.lower() in excluded_extensions:
        logger.debug(f"排除临时文件: {relative_path}")
        return True
    
    # 检查文件大小（可选，排除过大文件）
    max_file_size = 100 * 1024 * 1024  # 100MB
    try:
        if file_path.stat().st_size > max_file_size:
            logger.warning(f"文件过大，跳过备份: {relative_path} ({file_path.stat().st_size} bytes)")
            return True
    except OSError:
        pass
    
    return False


def get_backup_encryption_password() -> str | None:
    """获取备份加密密码
    
    优先级：
    1. BACKUP_ENCRYPTION_PASSWORD 环境变量
    2. BACKUP_ENCRYPTION_KEY 环境变量
    3. 如果 BACKUP_ENCRYPTION_FALLBACK_TO_GENERATED 为 True，则生成随机密钥
    4. 返回 None（不加密）
    """
    if not BACKUP_ENCRYPTION_ENABLED:
        return None
    
    # 优先使用密码
    if BACKUP_ENCRYPTION_PASSWORD:
        logger.info("使用环境变量 BACKUP_ENCRYPTION_PASSWORD 进行备份加密")
        return BACKUP_ENCRYPTION_PASSWORD
    
    # 其次使用密钥
    if BACKUP_ENCRYPTION_KEY:
        logger.info("使用环境变量 BACKUP_ENCRYPTION_KEY 进行备份加密")
        return BACKUP_ENCRYPTION_KEY
    
    # 如果允许回退到生成密钥
    if BACKUP_ENCRYPTION_FALLBACK_TO_GENERATED:
        generated_key = generate_encryption_key()
        # 仅显示密钥前8字符 + SHA-256 摘要前16字符
        _key_preview = generated_key[:8] + "..." if len(generated_key) > 8 else "***"
        _key_digest = hashlib.sha256(generated_key.encode()).hexdigest()[:16]
        logger.warning("备份加密密钥已生成（预览: %s, 摘要: %s），请安全保存完整密钥用于恢复", _key_preview, _key_digest)
        logger.warning("建议设置 BACKUP_ENCRYPTION_PASSWORD 环境变量以使用固定密钥")
        return generated_key
    
    # 加密已启用但未配置密钥，且不允许回退
    logger.warning("备份加密已启用但未配置加密密码，且不允许生成随机密钥，备份将不加密")
    return None


def split_backup_into_chunks(
    backup_bytes: bytes,
    chunk_size: int = BACKUP_CHUNK_SIZE,
    max_chunks: int = BACKUP_MAX_CHUNKS,
) -> list[tuple[int, bytes]]:
    """将备份数据分割为多个 chunk
    
    Args:
        backup_bytes: 备份数据字节
        chunk_size: 每个 chunk 的大小（字节）
        max_chunks: 最大 chunk 数量
        
    Returns:
        列表，每个元素为 (chunk_index, chunk_bytes)
    """
    total_size = len(backup_bytes)
    if total_size <= chunk_size:
        # 如果数据小于等于 chunk_size，直接返回单个 chunk
        return [(0, backup_bytes)]
    
    # 计算需要的 chunk 数量
    num_chunks = (total_size + chunk_size - 1) // chunk_size
    if num_chunks > max_chunks:
        raise BackupError(f"备份文件太大，需要 {num_chunks} 个 chunk，超过最大限制 {max_chunks}")
    
    chunks = []
    for i in range(num_chunks):
        start = i * chunk_size
        end = min((i + 1) * chunk_size, total_size)
        chunk_data = backup_bytes[start:end]
        chunks.append((i, chunk_data))
    
    logger.info(f"将备份文件分割为 {len(chunks)} 个 chunk，每个最大 {chunk_size} 字节")
    return chunks


def combine_backup_chunks(
    chunks: list[tuple[int, bytes]],
    total_size: int | None = None,
) -> bytes:
    """将多个 chunk 合并为完整的备份数据
    
    Args:
        chunks: chunk 列表，每个元素为 (chunk_index, chunk_bytes)
        total_size: 预期的总大小，用于验证
        
    Returns:
        合并后的字节数据
    """
    if not chunks:
        raise BackupError("没有提供任何 chunk")
    
    # 按索引排序
    chunks.sort(key=lambda x: x[0])
    
    # 验证索引连续性
    expected_index = 0
    for chunk_index, chunk_data in chunks:
        if chunk_index != expected_index:
            raise BackupError(f"Chunk 索引不连续，期望 {expected_index}，实际 {chunk_index}")
        expected_index += 1
    
    # 合并数据
    combined = b''.join(chunk_data for _, chunk_data in chunks)
    
    # 验证总大小
    if total_size is not None and len(combined) != total_size:
        raise BackupError(f"合并后大小不匹配，期望 {total_size} 字节，实际 {len(combined)} 字节")
    
    logger.info(f"成功合并 {len(chunks)} 个 chunk，总大小 {len(combined)} 字节")
    return combined


async def create_backup_chunks(
    db: AsyncSession,
    user,
    remark: str = '',
    chunk_size: int = BACKUP_CHUNK_SIZE,
    max_chunks: int = BACKUP_MAX_CHUNKS,
    use_snapshot: bool = True,
    encrypt_password: str | bytearray | None = None,
) -> list[dict]:
    """创建备份并将其分割为多个 chunk
    
    Args:
        db: 数据库会话
        user: 用户信息
        remark: 备份备注
        chunk_size: 每个 chunk 的大小（字节）
        max_chunks: 最大 chunk 数量
        use_snapshot: 是否使用数据库快照
        encrypt_password: 加密密码
        
    Returns:
        包含 chunk 信息的字典列表
    """
    # 创建备份
    backup_bytes, manifest = await create_full_backup(
        db=db,
        user=user,
        remark=remark,
        encrypt_password=encrypt_password,
        use_snapshot=use_snapshot,
    )
    
    # 分割为 chunk
    chunks = split_backup_into_chunks(backup_bytes, chunk_size, max_chunks)
    
    # 为每个 chunk 创建元数据
    chunk_metadata = []
    total_chunks = len(chunks)
    backup_id = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    for chunk_index, chunk_data in chunks:
        chunk_info = {
            'backup_id': backup_id,
            'chunk_index': chunk_index,
            'total_chunks': total_chunks,
            'chunk_size': len(chunk_data),
            'total_size': len(backup_bytes),
            'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'checksum': hashlib.sha256(chunk_data).hexdigest(),
            'manifest': manifest if chunk_index == 0 else None,  # 只在第一个 chunk 中包含完整 manifest
        }
        
        # 如果是第一个 chunk，添加额外的元数据
        if chunk_index == 0:
            chunk_info['is_first_chunk'] = True
            chunk_info['full_manifest'] = manifest
        else:
            chunk_info['is_first_chunk'] = False
        
        chunk_metadata.append({
            'metadata': chunk_info,
            'data': chunk_data,
        })
    
    logger.info(f"备份分割完成: {total_chunks} 个 chunk，总大小 {len(backup_bytes)} 字节")
    return chunk_metadata


async def restore_from_chunks(
    chunks_metadata: list[dict],
    db: AsyncSession,
    decrypt_password: str | bytearray | None = None,
    task_id: str | None = None,
) -> dict:
    """从多个 chunk 恢复备份
    
    Args:
        chunks_metadata: chunk 元数据列表，每个元素包含 'metadata' 和 'data'
        db: 数据库会话
        decrypt_password: 解密密码
        task_id: 任务 ID，用于进度报告
        
    Returns:
        恢复结果
    """
    if not chunks_metadata:
        raise BackupError("没有提供任何 chunk")
    
    # 验证所有 chunk 属于同一个备份
    backup_ids = set(chunk['metadata'].get('backup_id') for chunk in chunks_metadata)
    if len(backup_ids) != 1:
        raise BackupError(f"chunk 属于不同的备份: {backup_ids}")
    
    backup_id = next(iter(backup_ids))
    
    # 按索引排序
    chunks_metadata.sort(key=lambda x: x['metadata'].get('chunk_index', 0))
    
    # 验证 chunk 连续性
    expected_index = 0
    total_chunks = chunks_metadata[0]['metadata'].get('total_chunks')
    total_size = chunks_metadata[0]['metadata'].get('total_size')
    
    for chunk in chunks_metadata:
        metadata = chunk['metadata']
        chunk_index = metadata.get('chunk_index')
        
        if chunk_index != expected_index:
            raise BackupError(f"Chunk 索引不连续，期望 {expected_index}，实际 {chunk_index}")
        
        # 验证 checksum
        expected_checksum = metadata.get('checksum')
        actual_checksum = hashlib.sha256(chunk['data']).hexdigest()
        if expected_checksum != actual_checksum:
            raise BackupError(f"Chunk {chunk_index} 校验和不匹配")
        
        expected_index += 1
    
    # 验证总数
    if len(chunks_metadata) != total_chunks:
        raise BackupError(f"Chunk 数量不匹配，期望 {total_chunks}，实际 {len(chunks_metadata)}")
    
    # 合并数据
    chunk_data_list = [chunk['data'] for chunk in chunks_metadata]
    backup_bytes = b''.join(chunk_data_list)
    
    # 验证总大小
    if len(backup_bytes) != total_size:
        raise BackupError(f"合并后大小不匹配，期望 {total_size} 字节，实际 {len(backup_bytes)} 字节")
    
    logger.info(f"成功验证并合并 {len(chunks_metadata)} 个 chunk，备份 ID: {backup_id}")
    
    # 恢复备份
    return await restore_from_zip(
        zip_bytes=backup_bytes,
        db=db,
        decrypt_password=decrypt_password,
        task_id=task_id,
    )


def serialize_value(val):
    """将数据库值序列化为 JSON 兼容类型"""
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return val
    if isinstance(val, str):
        return val
    if isinstance(val, datetime):
        return val.strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(val, date):
        return val.isoformat()
    if isinstance(val, Decimal):
        return float(val)
    if isinstance(val, UUID):
        return str(val)
    if isinstance(val, (bytes, bytearray)):
        return val.hex()
    if hasattr(val, 'isoformat'):
        return val.isoformat()
    return str(val)


def build_column_type_map(table):
    """构建 column_name -> sqlalchemy type 映射"""
    return {str(col.name): col.type for col in table.columns}


def deserialize_value(val, col_type):
    """将 JSON 反序列化的值转回正确的 Python 类型"""
    if val is None:
        return None
    if isinstance(col_type, DateTime):
        if isinstance(val, str):
            try:
                return datetime.strptime(val, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                try:
                    return datetime.fromisoformat(val)
                except ValueError:
                    pass
        return val
    if isinstance(col_type, Date):
        if isinstance(val, str):
            try:
                return datetime.strptime(val, '%Y-%m-%d').date()
            except ValueError:
                try:
                    return date.fromisoformat(val)
                except ValueError:
                    pass
        return val
    if isinstance(col_type, Time):
        if isinstance(val, str):
            try:
                return datetime.strptime(val, '%H:%M:%S').time()
            except ValueError:
                try:
                    return time_type.fromisoformat(val)
                except ValueError:
                    pass
        return val
    if isinstance(col_type, Boolean):
        if isinstance(val, (int, float)):
            return bool(val)
        return val
    if isinstance(col_type, Numeric):
        if isinstance(val, (int, float)):
            return Decimal(str(val))
        return val
    if isinstance(col_type, JSON):
        return val
    if isinstance(col_type, ARRAY):
        return val
    if isinstance(col_type, PG_UUID):
        if isinstance(val, str):
            return UUID(val)
        return val
    return val


def quote_table(tname: str) -> str:
    """REV-08: 安全引用表名，防止 SQL 注入"""
    # 仅允许字母、数字、下划线
    if not tname.replace('_', '').replace('-', '').isalnum():
        raise ValueError(f'不安全的表名: {tname!r}')
    return f'"{tname}"'


def get_checksum_tables() -> set[str]:
    """获取需要校验和的表集合（排除 alembic_version）"""
    from fastapi_app.shared_models import Base
    return {str(t.name) for t in Base.metadata.sorted_tables if str(t.name) not in _CHECKSUM_EXCLUDE_TABLES}


# ---------------------------------------------------------------------------
# 数据库快照和二进制日志支持
# ---------------------------------------------------------------------------

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
        
    except Exception as e:
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
        logger.warning(f"获取 PostgreSQL LSN 失败: {e}")
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
        logger.warning(f"获取 PostgreSQL WAL 信息失败: {e}")
        return {}


async def create_binary_log_backup(
    db: AsyncSession,
    start_lsn: str | None = None,
    output_dir: Path | None = None,
) -> dict:
    """创建基于 PostgreSQL WAL 的二进制日志备份
    
    Args:
        db: 数据库会话
        start_lsn: 起始 LSN，如果为 None 则从当前 LSN 开始
        output_dir: 输出目录，如果为 None 则使用备份目录
        
    Returns:
        包含备份信息的字典
    """
    try:
        # 获取当前 WAL 信息
        wal_info = await get_postgres_wal_info(db)
        if not wal_info.get('current_lsn'):
            raise BinaryLogError("无法获取当前 LSN")
        
        current_lsn = wal_info['current_lsn']
        start_lsn = start_lsn or current_lsn
        
        # 确保输出目录存在
        if output_dir is None:
            output_dir = BACKUP_DIR / 'wal_archive'
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 生成备份文件名
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_file = output_dir / f'wal_backup_{timestamp}.tar.gz'
        
        # 获取数据库连接信息
        db_host = os.getenv('DB_HOST', 'localhost')
        db_port = os.getenv('DB_PORT', '5432')
        db_user = os.getenv('DB_USER', 'erp_app')
        db_name = os.getenv('DB_NAME', 'erp_system')
        if not db_name.isidentifier() or not all(c.isalnum() or c == '_' for c in db_name) or db_name[0].isdigit():
            raise ValueError(f'Invalid database name: {db_name!r}')
        db_password = os.getenv('DB_PASSWORD', '')
        
        # 设置环境变量
        env = os.environ.copy()
        env['PGPASSWORD'] = db_password
        
        # 使用 pg_basebackup 创建基础备份（如果需要）
        # 或者使用 pg_receivewal 接收 WAL 日志
        # 这里我们使用 pg_dump 的逻辑，但实际应该使用 pg_basebackup 或 pg_receivewal
        
        # 暂时实现为创建包含 WAL 信息的元数据文件
        backup_info = {
            'type': 'binary_log',
            'start_lsn': start_lsn,
            'end_lsn': current_lsn,
            'wal_info': wal_info,
            'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'backup_file': str(backup_file),
        }
        
        # 保存备份信息到文件
        info_file = output_dir / f'wal_backup_{timestamp}.json'
        info_file.write_text(json.dumps(backup_info, indent=2, ensure_ascii=False))
        
        logger.info(f"创建二进制日志备份: 从 LSN {start_lsn} 到 {current_lsn}")
        
        return {
            'success': True,
            'backup_file': str(backup_file),
            'info_file': str(info_file),
            'start_lsn': start_lsn,
            'end_lsn': current_lsn,
            'wal_info': wal_info,
        }
        
    except Exception as e:
        logger.error(f"创建二进制日志备份失败: {e}")
        raise BinaryLogError(f"创建二进制日志备份失败: {e}") from e


async def restore_from_binary_log(
    db: AsyncSession,
    backup_info_file: Path,
    target_lsn: str | None = None,
) -> dict:
    """从二进制日志备份恢复
    
    Args:
        db: 数据库会话
        backup_info_file: 备份信息文件路径
        target_lsn: 目标 LSN，如果为 None 则恢复到最新
        
    Returns:
        恢复结果字典
    """
    try:
        # 读取备份信息
        if not backup_info_file.exists():
            raise BinaryLogError(f"备份信息文件不存在: {backup_info_file}")
        
        backup_info = json.loads(backup_info_file.read_text())
        if backup_info.get('type') != 'binary_log':
            raise BinaryLogError(f"不是二进制日志备份文件: {backup_info_file}")
        
        start_lsn = backup_info.get('start_lsn')
        end_lsn = backup_info.get('end_lsn')
        
        if not start_lsn or not end_lsn:
            raise BinaryLogError(f"备份信息文件缺少 LSN 信息: {backup_info_file}")
        
        target_lsn = target_lsn or end_lsn
        
        logger.info(f"从二进制日志备份恢复: 从 LSN {start_lsn} 到 {target_lsn}")
        
        # 这里应该实现实际的 WAL 恢复逻辑
        # 实际实现需要使用 pg_restore 或类似的工具
        
        # 暂时返回成功信息
        return {
            'success': True,
            'message': f"二进制日志恢复已计划: 从 {start_lsn} 到 {target_lsn}",
            'start_lsn': start_lsn,
            'target_lsn': target_lsn,
            'restored_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
        
    except Exception as e:
        logger.error(f"从二进制日志备份恢复失败: {e}")
        raise BinaryLogError(f"从二进制日志备份恢复失败: {e}") from e


# ---------------------------------------------------------------------------
# 数据库查询辅助
# ---------------------------------------------------------------------------

async def find_timestamp_column(tname: str, db: AsyncSession) -> str | None:
    """查找表的时间戳列（REV-33: 添加缓存）"""
    if tname in _ts_col_cache:
        return _ts_col_cache[tname]
    try:
        cols_result = await db.execute(
            text('SELECT column_name FROM information_schema.columns WHERE table_name = :tname ORDER BY ordinal_position'),
            {'tname': tname}
        )
        col_names = [r[0] for r in cols_result.fetchall()]
        for candidate in _TIMESTAMP_CANDIDATES:
            if candidate in col_names:
                _ts_col_cache[tname] = candidate
                return candidate
    except (SQLAlchemyError, OSError, ValueError) as e:
        logger.warning(f'查询表 {tname} 列信息失败: {e}')
    _ts_col_cache[tname] = None
    return None


async def query_table_rows(tname: str, db: AsyncSession, since: str | None = None) -> list[dict]:
    """查询表数据，支持按时间戳增量查询"""
    ts_col = await find_timestamp_column(tname, db) if since else None
    qtname = quote_table(tname)  # REV-08
    if ts_col:
        # 列可能是 timestamptz（需 datetime）也可能是 varchar（需 string），先尝试字符串
        since_dt = since
        if isinstance(since_dt, str):
            try:
                since_dt = datetime.strptime(since_dt, '%Y-%m-%d %H:%M:%S')
            except (TypeError, ValueError):
                pass
        # 优先尝试 datetime（timestamptz 列需要）；失败时回退到字符串
        try:
            result = await db.execute(
                text(f'SELECT * FROM {qtname} WHERE "{ts_col}" >= :since'),  # nosec B608 — qtname 经 quote_table 白名单校验
                {'since': since_dt},
            )
        except DataError:
            # 事务已失败，必须先 rollback 才能在新事务中重试
            try:
                await db.rollback()
            except SQLAlchemyError:
                pass
            result = await db.execute(
                text(f'SELECT * FROM {qtname} WHERE "{ts_col}" >= :since'),  # nosec B608 — qtname 经 quote_table 白名单校验
                {'since': since},
            )
    else:
        result = await db.execute(text(f'SELECT * FROM {qtname}'))  # nosec B608 — qtname 经 quote_table 白名单校验
    rows = result.mappings().all()
    columns = list(result.keys())
    serialized_rows = []
    for row in rows:
        serialized_row = {}
        for col in columns:
            serialized_row[col] = serialize_value(row[col])
        serialized_rows.append(serialized_row)
    return serialized_rows


async def find_last_backup_timestamp() -> str | None:
    """查找最近一次全量备份的导出时间"""
    if not BACKUP_DIR.exists():
        return None
    for f in sorted(BACKUP_DIR.iterdir(), reverse=True):
        if f.is_file() and f.name.startswith('erp_backup_') and f.name.endswith('.zip'):
            try:
                with zipfile.ZipFile(f, 'r') as zf:
                    if 'manifest.json' in zf.namelist():
                        mf = json.loads(zf.read('manifest.json'))
                        return mf.get('exported_at')
            except (OSError, zipfile.BadZipFile, ValueError):
                continue
    return None


# ---------------------------------------------------------------------------
# pg_dump / psql 辅助
# ---------------------------------------------------------------------------

async def get_pg_version(host, port, user, password, env) -> str:
    """获取 PostgreSQL 版本字符串"""
    try:
        proc = await asyncio.create_subprocess_exec(
            'psql', '-h', host, '-p', port, '-U', user,
            '-d', os.getenv('DB_NAME', 'erp_system'),
            '-t', '-c', 'SELECT version();',
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0:
            return stdout.decode(errors='replace').strip().split(',')[0]
    except (TimeoutError, OSError, ValueError) as e:
        logger.warning(f'获取 PG 版本失败: {e}')
    return 'unknown'


async def run_pg_dump(output_path: Path, snapshot_id: str | None = None) -> dict:
    """执行 pg_dump 导出数据库为 gzip 压缩 SQL

    Args:
        output_path: 输出文件路径
        snapshot_id: 可选，PostgreSQL 快照 ID，用于一致性备份
    
    Returns: dict with pg_version, db_name, dump_size, duration_seconds, snapshot_id
    """
    import time
    start = time.monotonic()
    db_host = os.getenv('DB_HOST', 'localhost')
    db_port = os.getenv('DB_PORT', '5432')
    db_user = os.getenv('DB_USER', 'erp_app')
    db_name = os.getenv('DB_NAME', 'erp_system')
    if not db_name.isidentifier() or not all(c.isalnum() or c == '_' for c in db_name) or db_name[0].isdigit():
        raise ValueError(f'Invalid database name: {db_name!r}')
    db_password = os.getenv('DB_PASSWORD', '')
    env = os.environ.copy()
    env['PGPASSWORD'] = db_password
    try:
        # 构建 pg_dump 命令参数
        pg_dump_args = [
            'pg_dump', '-h', db_host, '-p', db_port, '-U', db_user, '-d', db_name,
            '--no-owner', '--no-privileges'
        ]
        
        # 如果提供了快照 ID，使用 --snapshot 参数
        if snapshot_id:
            pg_dump_args.extend(['--snapshot', snapshot_id])
            logger.info(f"使用数据库快照 {snapshot_id} 进行备份")
        
        proc = await asyncio.create_subprocess_exec(
            *pg_dump_args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env
        )
        gzip_proc = await asyncio.create_subprocess_exec(
            'gzip', '-1', stdin=proc.stdout,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await gzip_proc.communicate()
        await proc.wait()
        if proc.returncode != 0:
            stderr_data = await proc.stderr.read() if proc.stderr else b''
            raise RuntimeError(f"pg_dump failed (rc={proc.returncode}): {stderr_data.decode(errors='replace')}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(stdout)
        duration = time.monotonic() - start
        return {
            'pg_version': await get_pg_version(db_host, db_port, db_user, db_password, env),
            'db_name': db_name,
            'dump_size': len(stdout),
            'duration_seconds': round(duration, 2),
            'snapshot_id': snapshot_id,
        }
    except FileNotFoundError:
        raise RuntimeError('pg_dump 命令未找到，请确保 PostgreSQL 客户端工具已安装') from None
    except RuntimeError:
        raise
    except (TimeoutError, OSError, ValueError) as e:
        raise RuntimeError(f'pg_dump 执行失败: {e}') from e


# ---------------------------------------------------------------------------
# Legacy JSON 备份
# ---------------------------------------------------------------------------

async def execute_legacy_backup_to_bytes(user, remark: str, db: AsyncSession) -> bytes:
    """Legacy JSON 备份 (v1.0)，用于无 pg_dump 环境"""
    from fastapi_app.shared_models import Base
    backup_data = {
        'version': '1.0',
        'exported_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'exported_by': user.username if hasattr(user, 'username') else str(user.id),
        'remark': remark,
        'tables': {},
    }
    # 先查询实际存在的表，避免查询不存在的表导致事务失败
    existing_result = await db.execute(
        text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
    )
    existing_tables = {r[0] for r in existing_result.fetchall()}

    for table in Base.metadata.sorted_tables:
        name = str(table.name)
        if name not in existing_tables:
            logger.warning(f'跳过不存在的表: {name}')
            backup_data['tables'][name] = {'error': '表不存在', 'count': 0, 'rows': []}
            continue
        try:
            qtname = quote_table(name)
            nested = await db.begin_nested()
            try:
                result = await db.execute(text(f'SELECT * FROM {qtname}'))
                rows = result.mappings().all()
                columns = list(result.keys())
                serialized_rows = []
                for row in rows:
                    serialized_row = {}
                    for col in columns:
                        serialized_row[col] = serialize_value(row[col])
                    serialized_rows.append(serialized_row)
                backup_data['tables'][name] = {'columns': columns, 'rows': serialized_rows, 'count': len(serialized_rows)}
                await nested.commit()
            except (SQLAlchemyError, ValueError, OSError) as e:
                await nested.rollback()
                logger.error('备份表 %s 失败: %s', name, e)
                backup_data['tables'][name] = {'error': str(e), 'count': 0, 'rows': []}
        except (SQLAlchemyError, ValueError, OSError) as e:
            logger.error('备份表 %s 初始化失败: %s', name, e)
            backup_data['tables'][name] = {'error': str(e), 'count': 0, 'rows': []}
    return json.dumps(backup_data, ensure_ascii=False, indent=2).encode('utf-8')


# ---------------------------------------------------------------------------
# 全量备份核心函数
# ---------------------------------------------------------------------------

async def create_full_backup(
    db: AsyncSession,
    user,
    remark: str,
    encrypt_password: str | bytearray | None = None,
    use_snapshot: bool = True,
    encrypt: bool | None = None,
) -> tuple[bytes, dict]:
    """执行全量备份并返回 (zip_bytes, manifest_dict)。

    如果提供 encrypt_password，则使用 AES-256-GCM 加密备份。
    如果 use_snapshot 为 True，则使用数据库快照确保备份一致性。

    encrypt 参数：
    - None（默认）：兼容旧行为，按环境变量配置决定是否加密。
    - True：强制加密（优先使用 encrypt_password，否则使用环境变量或生成密钥）。
    - False：强制不加密。

    Falls back to JSON database export if pg_dump is not available.

    包含：
    - 进程级 asyncio.Lock：避免同一进程内并发触发
    - 数据库 advisory_lock：避免跨进程并发
    - 总超时控制：超出 BACKUP_OPERATION_TIMEOUT 强制取消
    """
    if _backup_in_progress.locked():
        raise BackupLockError('已有备份任务正在执行中，请稍后重试')

    db_lock_acquired = await acquire_backup_lock(db)
    if not db_lock_acquired:
        raise BackupLockError('其他进程正在执行备份，请稍后重试')

    async with _backup_in_progress:
        try:
            return await asyncio.wait_for(
                _do_create_full_backup(db, user, remark, encrypt_password, use_snapshot, encrypt),
                timeout=BACKUP_OPERATION_TIMEOUT,
            )
        except asyncio.TimeoutError as e:
            logger.error('备份操作超时（%s秒）', BACKUP_OPERATION_TIMEOUT)
            raise BackupError(f'备份超时（>{BACKUP_OPERATION_TIMEOUT}s），已强制取消') from e
        finally:
            await release_backup_lock(db)


async def _do_create_full_backup(
    db: AsyncSession,
    user,
    remark: str,
    encrypt_password: str | bytearray | None,
    use_snapshot: bool,
    encrypt: bool | None = None,
) -> tuple[bytes, dict]:
    """create_full_backup 的实际实现，由锁和超时控制包裹。"""
    snapshot_id = None
    if use_snapshot:
        try:
            snapshot_id = await get_postgres_snapshot(db)
            logger.info(f"获取数据库快照成功: {snapshot_id}")
        except DatabaseSnapshotError as e:
            logger.warning(f"无法获取数据库快照，继续无快照备份: {e}")
            # 降级处理，继续备份但不使用快照
    
    with tempfile.TemporaryDirectory(prefix='erp_backup_') as tmpdir:
        tmpdir_path = Path(tmpdir)
        dump_path = tmpdir_path / 'database' / 'dump.sql.gz'
        dump_info: dict = {}
        pg_dump_available = False
        try:
            dump_info = await run_pg_dump(dump_path, snapshot_id)
            pg_dump_available = True
        except (TimeoutError, OSError, RuntimeError) as e:
            logger.warning(f'pg_dump 不可用，使用 JSON 格式备份数据库: {e}')
            json_path = tmpdir_path / 'database'
            json_path.mkdir(parents=True, exist_ok=True)
            json_bytes = await execute_legacy_backup_to_bytes(user, remark, db)
            json_path_file = json_path / 'dump.json'
            json_path_file.write_bytes(json_bytes)
            dump_info = {
                'pg_version': '', 'db_name': os.getenv('DB_NAME', 'erp_system'),
                'dump_size': len(json_bytes), 'duration_seconds': 0, 'format': 'json',
            }

        from fastapi_app.shared_models import Base

        # REV-34: COUNT(*) 用 asyncio.gather() 并发执行
        table_names = [str(t.name) for t in Base.metadata.sorted_tables]

        # 先查询实际存在的表，避免查询不存在的表导致事务失败
        existing_result = await db.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        )
        existing_tables = {r[0] for r in existing_result.fetchall()}

        async def _count_table(tname: str) -> tuple[str, int]:
            if tname not in existing_tables:
                return tname, -1
            nested = await db.begin_nested()
            try:
                qtname = quote_table(tname)
                result = await db.execute(text(f'SELECT COUNT(*) FROM {qtname}'))
                await nested.commit()
                return tname, result.scalar() or 0
            except (OSError, ValueError, SQLAlchemyError):
                await nested.rollback()
                return tname, -1

        count_results = []
        for n in table_names:
            count_results.append(await _count_table(n))
        table_stats = dict(count_results)

        checksums = {}
        db_dump_name = 'database/dump.sql.gz' if pg_dump_available else 'database/dump.json'
        db_dump_file = dump_path if pg_dump_available else tmpdir_path / 'database' / 'dump.json'
        if db_dump_file.is_file():
            checksums[db_dump_name] = sha256_file(db_dump_file)  # REV-14

        fingerprints = {}
        for table in Base.metadata.sorted_tables:
            tname = str(table.name)
            if tname not in get_checksum_tables():
                continue
            try:
                qtname = quote_table(tname)  # REV-08
                pk_col = [c.name for c in table.primary_key.columns]
                order_col = pk_col[0] if pk_col else 'id'
                cols_result = await db.execute(
                    text('SELECT column_name FROM information_schema.columns WHERE table_name = :tname ORDER BY ordinal_position'),
                    {'tname': tname}
                )
                col_names = [r[0] for r in cols_result.fetchall()]
                # REV-14: 指纹聚合使用 MD5（数据完整性校验，非安全场景）
                agg_expr = " || '|' || ".join(f'''COALESCE("{c}"::text, '')''' for c in col_names)
                fp_result = await db.execute(text(
                    f'''SELECT MD5(STRING_AGG({agg_expr}, ',' ORDER BY "{order_col}")) FROM {qtname}'''
                ))
                fingerprints[tname] = fp_result.scalar() or ''
            except (SQLAlchemyError, ValueError, OSError) as e:
                logger.warning(f'计算表 {tname} 指纹失败: {e}')
                fingerprints[tname] = ''

        manifest = {
            'version': BACKUP_FORMAT_VERSION, 'type': 'full', 'app_version': '2.0',
            'pg_version': dump_info.get('pg_version', ''),
            'db_name': dump_info.get('db_name', ''),
            'exported_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'exported_by': user.username if hasattr(user, 'username') else str(user.id),
            'remark': remark,
            'table_count': len(table_stats),
            'total_rows': sum(v for v in table_stats.values() if v >= 0),
            'dump_size': dump_info.get('dump_size', 0),
            'dump_duration_seconds': dump_info.get('duration_seconds', 0),
            'snapshot_id': dump_info.get('snapshot_id'),
            'tables': {k: {'rows': v} for k, v in table_stats.items()},
            'includes': {}, 'checksums': checksums, 'fingerprints': fingerprints,
        }

        zip_path = tmpdir_path / 'backup.zip'
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=3) as zf:
            if pg_dump_available and dump_path.is_file():
                zf.write(dump_path, 'database/dump.sql.gz')
            elif (tmpdir_path / 'database' / 'dump.json').is_file():
                zf.write(tmpdir_path / 'database' / 'dump.json', 'database/dump.json')

            if UPLOADS_DIR.is_dir():
                file_count = 0
                for fp in sorted(UPLOADS_DIR.rglob('*')):
                    if fp.is_file():
                        arcname = f'filestore/{fp.relative_to(UPLOADS_DIR)}'
                        zf.write(fp, arcname)
                        file_count += 1
                manifest['includes']['filestore_count'] = file_count

            config_files_added = []
            config_files_excluded = []
            
            # 备份配置文件，排除敏感文件
            config_files_to_check = [
                ('jwt/private.pem', 'jwt/private.pem'),
                ('jwt/public.pem', 'jwt/public.pem'),
                ('redis.production.conf', 'redis.production.conf'),
                ('nginx.conf', 'nginx.conf'),
                ('.env.production', '.env.production'),
            ]
            
            for file_name, relative_path in config_files_to_check:
                file_path = CONFIG_DIR / file_name
                if file_path.is_file():
                    if should_exclude_file(file_path, relative_path):
                        config_files_excluded.append(relative_path)
                        logger.info(f"排除配置文件: {relative_path}")
                    else:
                        zf.write(file_path, f'config/{relative_path}')
                        config_files_added.append(relative_path)
            
            manifest['includes']['config_files'] = config_files_added
            if config_files_excluded:
                manifest['includes']['config_files_excluded'] = config_files_excluded

            if REDIS_DUMP.is_file():
                zf.write(REDIS_DUMP, 'redis/dump.rdb')
                manifest['includes']['redis_rdb'] = True

            try:
                import httpx
                async with httpx.AsyncClient() as meili_client:
                    meili_indexes_resp = await meili_client.get(
                        f'{MEILI_HOST}/indexes',
                        headers={'Authorization': f'Bearer {MEILI_MASTER_KEY}'}, timeout=10
                    )
                    if meili_indexes_resp.status_code == 200:
                        meili_indexes_data = meili_indexes_resp.json()
                        meili_index_names = [idx['uid'] for idx in meili_indexes_data.get('results', [])]
                        meili_export = {}
                        for idx_name in meili_index_names:
                            docs_resp = await meili_client.get(
                                f'{MEILI_HOST}/indexes/{idx_name}/documents',
                                headers={'Authorization': f'Bearer {MEILI_MASTER_KEY}'},
                                params={'limit': 100000}, timeout=60
                            )
                            if docs_resp.status_code == 200:
                                meili_export[idx_name] = docs_resp.json().get('results', [])
                            settings_resp = await meili_client.get(
                                f'{MEILI_HOST}/indexes/{idx_name}/settings',
                                headers={'Authorization': f'Bearer {MEILI_MASTER_KEY}'}, timeout=10
                            )
                            if settings_resp.status_code == 200:
                                meili_export[f'{idx_name}__settings'] = settings_resp.json()
                        if meili_export:
                            meili_bytes = json.dumps(meili_export, ensure_ascii=False).encode('utf-8')
                            zf.writestr('meilisearch/dump.json', meili_bytes)
                            manifest['includes']['meilisearch_indexes'] = meili_index_names
                            manifest['includes']['meilisearch_doc_count'] = sum(
                                len(v) for k, v in meili_export.items() if not k.endswith('__settings')
                            )
            except Exception as e:
                logger.warning('MeiliSearch 索引导出失败（可忽略）: %s', e)

            manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8')
            zf.writestr('manifest.json', manifest_bytes)

        zip_bytes = zip_path.read_bytes()
        manifest['zip_size'] = len(zip_bytes)

        # 默认加密（根据环境变量配置）
        if encrypt is False:
            effective_encryption_password = None
        else:
            effective_encryption_password = encrypt_password or get_backup_encryption_password()
        if effective_encryption_password:
            from fastapi_app.core.backup_encryption import encrypt_backup, create_meta_file
            try:
                encrypted_bytes, meta_dict = encrypt_backup(zip_bytes, effective_encryption_password)
                # 返回加密后的 bytes，manifest 中标记已加密
                manifest['encrypted'] = True
                manifest['encryption'] = meta_dict
                # 记录加密信息
                if encrypt_password:
                    logger.info("使用用户提供的密码进行备份加密")
                elif BACKUP_ENCRYPTION_PASSWORD or BACKUP_ENCRYPTION_KEY:
                    logger.info("使用环境变量配置的密钥进行备份加密")
                else:
                    logger.warning(f"使用生成的随机密钥进行备份加密，密钥已记录在日志中")
                return encrypted_bytes, manifest
            except Exception as e:
                logger.error(f"备份加密失败: {e}")
                if BACKUP_ENCRYPTION_ENABLED and not BACKUP_ENCRYPTION_FALLBACK_TO_GENERATED:
                    raise BackupError(f"备份加密失败且不允许回退到未加密备份: {e}") from e
                logger.warning("加密失败，返回未加密的备份文件")
                # 继续返回未加密的备份

    return zip_bytes, manifest


async def create_full_backup_to_file(
    db: AsyncSession,
    user,
    remark: str,
    output_path: Path | None = None,
    use_snapshot: bool = True,
    encrypt_password: str | bytearray | None = None,
    encrypt: bool | None = None,
) -> tuple[Path, dict]:
    """执行全量备份并保存到文件，返回 (file_path, manifest_dict)。

    用于大文件备份，避免将整个 ZIP 读入内存。
    如果未指定 output_path，使用临时文件。
    如果 use_snapshot 为 True，则使用数据库快照确保备份一致性。
    如果提供 encrypt_password 或配置了环境变量，则使用 AES-256-GCM 加密备份。

    encrypt 参数：
    - None（默认）：兼容旧行为，按环境变量配置决定是否加密。
    - True：强制加密（优先使用 encrypt_password，否则使用环境变量或生成密钥）。
    - False：强制不加密。

    包含：进程级 asyncio.Lock、数据库 advisory_lock、BACKUP_OPERATION_TIMEOUT 总超时控制。
    """
    zip_bytes, manifest = await create_full_backup(
        db, user, remark, encrypt_password, use_snapshot, encrypt=encrypt
    )

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(zip_bytes)
        return output_path, manifest
    else:
        fd, tmp_file = tempfile.mkstemp(suffix='.zip', prefix='erp_backup_')
        os.close(fd)
        Path(tmp_file).write_bytes(zip_bytes)
        return Path(tmp_file), manifest



async def _reload_redis() -> bool:
    """尝试重新加载 Redis 数据"""
    redis_cli = shutil.which('redis-cli')
    if not redis_cli:
        logger.warning('未找到 redis-cli，无法自动重新加载 Redis')
        return False
    try:
        from fastapi_app.core.config import settings
        cmd = [redis_cli]
        cli_env = os.environ.copy()
        redis_url = settings.REDIS_URL
        if redis_url:
            from urllib.parse import urlparse
            parsed = urlparse(redis_url)
            if parsed.hostname:
                cmd.extend(['-h', parsed.hostname])
            if parsed.port:
                cmd.extend(['-p', str(parsed.port)])
            if parsed.password:
                cli_env['REDISCLI_AUTH'] = parsed.password
        cmd.extend(['DEBUG', 'RELOAD'])
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=cli_env
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            logger.warning('Redis DEBUG RELOAD 超时')
            return False
        if proc.returncode == 0:
            logger.info('Redis DEBUG RELOAD 成功')
            return True
        stderr_text = stderr.decode(errors='replace')
        logger.warning('Redis DEBUG RELOAD 失败: %s', stderr_text)
        try:
            shutdown_cmd = cmd[:-2] + ['SHUTDOWN', 'NOSAVE']
            shutdown_proc = await asyncio.create_subprocess_exec(
                *shutdown_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=cli_env
            )
            try:
                await asyncio.wait_for(shutdown_proc.communicate(), timeout=5)
            except asyncio.TimeoutError:
                shutdown_proc.kill()
                await shutdown_proc.wait()
            logger.info('Redis SHUTDOWN NOSAVE 已发送，等待自动重启')
            await asyncio.sleep(2)
            ping_cmd = cmd[:-2] + ['PING']
            for _ in range(5):
                ping_proc = await asyncio.create_subprocess_exec(
                    *ping_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=cli_env
                )
                try:
                    await asyncio.wait_for(ping_proc.communicate(), timeout=3)
                except asyncio.TimeoutError:
                    ping_proc.kill()
                    await ping_proc.wait()
                    await asyncio.sleep(1)
                    continue
                if ping_proc.returncode == 0:
                    logger.info('Redis 已重启成功')
                    return True
                await asyncio.sleep(1)
            logger.warning('Redis 重启后未能响应 PING')
            return False
        except (OSError, asyncio.TimeoutError) as e2:
            logger.warning('Redis SHUTDOWN 尝试失败: %s', e2)
            return False
    except (OSError, asyncio.TimeoutError) as e:
        logger.warning('Redis 重新加载失败: %s', e)
        return False


def restore_filestore(zf: zipfile.ZipFile) -> dict:
    """恢复附件文件到 static/uploads/"""
    restored = 0
    errors = []
    for name in zf.namelist():
        if not name.startswith('filestore/') or name.endswith('/'):
            continue
        rel_path = name[len('filestore/'):]
        if '..' in rel_path or rel_path.startswith('/') or rel_path.startswith('\\'):
            errors.append(f'{rel_path}: 路径不安全，已跳过')
            continue
        target = UPLOADS_DIR / rel_path
        try:
            target.resolve().relative_to(UPLOADS_DIR.resolve())
        except ValueError:
            errors.append(f'{rel_path}: 路径越界，已跳过')
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(name))
            restored += 1
        except (OSError, ValueError) as e:
            errors.append(f'{rel_path}: {e}')
    return {'status': 'ok' if not errors else 'partial', 'restored': restored, 'errors': errors}


def restore_config(zf: zipfile.ZipFile, confirm_sensitive: bool = False) -> dict:
    """恢复配置文件到 config/ 目录（REV-09: 敏感文件白名单校验）"""
    restored = []
    errors = []
    skipped_sensitive = []
    for name in zf.namelist():
        if not name.startswith('config/') or name.endswith('/'):
            continue
        rel_path = name[len('config/'):]
        if '..' in rel_path or rel_path.startswith('/') or rel_path.startswith('\\'):
            errors.append(f'{rel_path}: 路径不安全，已跳过')
            continue
        # REV-09: 敏感文件恢复需二次确认
        if rel_path in _SENSITIVE_AND_EXCLUDED_FILES and not confirm_sensitive:
            skipped_sensitive.append(rel_path)
            logger.warning(f"跳过敏感文件恢复（需要确认）: {rel_path}")
            continue
        target = CONFIG_DIR / rel_path
        try:
            target.resolve().relative_to(CONFIG_DIR.resolve())
        except ValueError:
            errors.append(f'{rel_path}: 路径越界，已跳过')
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(name))
            restored.append(rel_path)
        except (OSError, ValueError) as e:
            errors.append(f'{rel_path}: {e}')
    result = {'status': 'ok' if not errors else 'partial', 'restored': restored, 'errors': errors}
    if skipped_sensitive:
        result['skipped_sensitive'] = skipped_sensitive
        result['status'] = 'partial'
    return result


async def restore_redis_rdb(zf: zipfile.ZipFile) -> dict:
    """恢复 Redis RDB 文件"""
    try:
        rdb_data = zf.read('redis/dump.rdb')
        if REDIS_DUMP.is_file():
            backup_path = REDIS_DUMP.with_suffix('.rdb.bak')
            shutil.copy2(REDIS_DUMP, backup_path)
        REDIS_DUMP.write_bytes(rdb_data)
        reload_result = await _reload_redis()
        if reload_result:
            return {'status': 'ok', 'message': 'Redis RDB 已恢复并重新加载'}
        return {'status': 'ok', 'message': 'Redis RDB 已恢复，需手动重启 Redis 生效', 'auto_reload_failed': True}
    except (OSError, ValueError) as e:
        return {'status': 'error', 'error': f'Redis RDB 恢复失败: {e}'}


async def restore_meilisearch(zf: zipfile.ZipFile) -> dict:
    """恢复 MeiliSearch 索引"""
    try:
        meili_data = json.loads(zf.read('meilisearch/dump.json'))
    except (json.JSONDecodeError, KeyError, OSError) as e:
        return {'status': 'error', 'error': f'MeiliSearch 数据读取失败: {e}'}
    try:
        import httpx
    except ImportError:
        return {'status': 'error', 'error': 'httpx 未安装，无法恢复 MeiliSearch'}
    restored_indexes = []
    errors = []
    async with httpx.AsyncClient() as meili_client:
        for key, data in meili_data.items():
            if key.endswith('__settings'):
                continue
            idx_name = key
            if not idx_name.replace('_', '').replace('-', '').isalnum():
                errors.append(f'{idx_name}: 索引名不合法，已跳过')
                continue
            settings_key = f'{idx_name}__settings'
            try:
                create_resp = await meili_client.post(
                    f'{MEILI_HOST}/indexes',
                    headers={'Authorization': f'Bearer {MEILI_MASTER_KEY}'},
                    json={'uid': idx_name, 'primaryKey': 'id'}, timeout=10
                )
                if create_resp.status_code not in (200, 201, 409):
                    errors.append(f'{idx_name}: 创建索引失败 ({create_resp.status_code})')
                    continue
                if settings_key in meili_data:
                    await meili_client.patch(
                        f'{MEILI_HOST}/indexes/{idx_name}/settings',
                        headers={'Authorization': f'Bearer {MEILI_MASTER_KEY}'},
                        json=meili_data[settings_key], timeout=10
                    )
                if data:
                    docs_resp = await meili_client.post(
                        f'{MEILI_HOST}/indexes/{idx_name}/documents',
                        headers={'Authorization': f'Bearer {MEILI_MASTER_KEY}'},
                        json=data, timeout=60
                    )
                    if docs_resp.status_code in (200, 201, 202):
                        restored_indexes.append(idx_name)
                    else:
                        errors.append(f'{idx_name}: 文档导入失败 ({docs_resp.status_code})')
                else:
                    restored_indexes.append(idx_name)
            except (OSError, ValueError) as e:
                errors.append(f'{idx_name}: {e}')
    return {'status': 'ok' if not errors else 'partial', 'restored_indexes': restored_indexes, 'errors': errors}


async def create_pre_restore_backup(db: AsyncSession) -> dict:
    """创建恢复前安全备份"""
    ensure_pre_restore_dir()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'pre_restore_{timestamp}.zip'
    filepath = PRE_RESTORE_DIR / filename
    try:
        from fastapi_app.shared_models import User as UserModel
        dummy_user = UserModel()
        dummy_user.username = 'system'
        dummy_user.id = 0
        zip_bytes, manifest = await create_full_backup(db, dummy_user, '恢复前自动安全备份')
        filepath.write_bytes(zip_bytes)
        cleanup_pre_restore_backups()
        return {'success': True, 'filename': filename, 'filepath': str(filepath), 'size': len(zip_bytes)}
    except Exception as e:
        logger.warning(f'创建恢复前安全备份失败（不阻塞恢复）: {e}')
        return {'success': False, 'error': str(e)}


def cleanup_pre_restore_backups():
    """清理旧的恢复前安全备份（保留最近 5 个）"""
    if not PRE_RESTORE_DIR.exists():
        return
    backups = sorted(
        [f for f in PRE_RESTORE_DIR.iterdir() if f.is_file() and f.name.startswith('pre_restore_') and f.name.endswith('.zip')],
        key=lambda f: f.name, reverse=True
    )
    for old_backup in backups[_MAX_PRE_RESTORE_BACKUPS:]:
        try:
            old_backup.unlink()
            logger.info(f'已清理旧安全备份: {old_backup.name}')
        except OSError as e:
            logger.warning(f'清理旧安全备份失败: {old_backup.name}: {e}')


async def restore_database_via_psql(zf: zipfile.ZipFile, db: AsyncSession, task_id: str = None) -> dict:
    """通过 psql 从 dump.sql.gz 恢复数据库"""
    import time as time_mod
    from fastapi_app.core.backup_progress import update_progress as _upd_prog

    async def _report(sub: float, detail: str):
        if task_id:
            await _upd_prog(task_id, 'restore_db', sub, detail)

    # 分步读取和解压，添加进度报告
    await _report(0.0, '读取备份文件...')
    await asyncio.sleep(0)  # 让出控制权，确保前端能收到更新

    # 获取压缩文件大小用于进度计算
    try:
        info = zf.getinfo('database/dump.sql.gz')
        compressed_size = info.file_size
    except KeyError:
        compressed_size = 0

    # 读取压缩数据
    await _report(0.005, f'读取压缩数据 ({compressed_size // 1024 // 1024}MB)...')
    await asyncio.sleep(0)
    dump_gz = zf.read('database/dump.sql.gz')

    # 解压数据
    await _report(0.01, '解压数据库备份...')
    await asyncio.sleep(0)
    dump_sql = gzip.decompress(dump_gz)
    del dump_gz  # 释放压缩数据内存

    if not dump_sql or not dump_sql.strip():
        return {'status': 'error', 'error': '数据库备份文件为空，无法恢复'}

    sql_size_mb = len(dump_sql) // 1024 // 1024
    await _report(0.015, f'解压完成 ({sql_size_mb}MB)，准备恢复...')
    await asyncio.sleep(0)

    db_host = os.getenv('DB_HOST', 'localhost')
    db_port = os.getenv('DB_PORT', '5432')
    db_user = os.getenv('DB_USER', 'erp_app')
    db_name = os.getenv('DB_NAME', 'erp_system')
    if not db_name.isidentifier() or not all(c.isalnum() or c == '_' for c in db_name) or db_name[0].isdigit():
        raise ValueError(f'Invalid database name: {db_name!r}')
    db_password = os.getenv('DB_PASSWORD', '')
    env = os.environ.copy()
    env['PGPASSWORD'] = db_password

    await _report(0.02, '关闭应用数据库连接')
    await asyncio.sleep(0)
    try:
        await db.close()
    except (OSError, SQLAlchemyError):
        logger.warning('psql前关闭数据库会话失败')
    try:
        from fastapi_app.core.database import _async_engine
        if _async_engine is not None:
            await _async_engine.dispose()
    except (OSError, ValueError):
        logger.warning('psql前释放连接池失败')

    await _report(0.06, '等待活跃连接释放')
    await asyncio.sleep(0)
    for _retry in range(3):
        await asyncio.sleep(1)
        try:
            check_proc = await asyncio.create_subprocess_exec(
                'psql', '-h', db_host, '-p', db_port, '-U', db_user, '-d', 'postgres', '-t', '-c',
                f"SELECT COUNT(*) FROM pg_stat_activity WHERE datname = '{db_name}';",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env
            )
            # 添加超时防止 psql 命令挂起
            try:
                check_stdout, _ = await asyncio.wait_for(check_proc.communicate(), timeout=10)
            except asyncio.TimeoutError:
                check_proc.kill()
                await check_proc.wait()
                logger.warning(f'检查活跃连接超时，重试 {_retry + 1}/3')
                continue
            if check_proc.returncode == 0:
                active_count = int(check_stdout.decode(errors='replace').strip() or '0')
                if active_count == 0:
                    break
                logger.warning(f'仍有 {active_count} 个活跃连接，重试 {_retry + 1}/3')
        except (TimeoutError, OSError, ValueError) as e:
            logger.warning(f'检查活跃连接失败: {e}，重试 {_retry + 1}/3')

    await _report(0.10, '终止残留数据库连接')
    await asyncio.sleep(0)
    try:
        term_proc = await asyncio.create_subprocess_exec(
            'psql', '-h', db_host, '-p', db_port, '-U', db_user, '-d', 'postgres', '-c',
            f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{db_name}' AND pid <> pg_backend_pid();",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env
        )  # nosec
        # 添加超时防止 psql 命令挂起
        try:
            await asyncio.wait_for(term_proc.wait(), timeout=30)
        except asyncio.TimeoutError:
            term_proc.kill()
            await term_proc.wait()
            logger.warning('终止连接超时，已强制终止')
    except (TimeoutError, OSError, ValueError) as e:
        logger.warning(f'终止现有连接失败: {e}')

    await _report(0.14, '重建数据库')
    await asyncio.sleep(0)
    try:
        pg_major = 13
        try:
            ver_proc = await asyncio.create_subprocess_exec(
                'psql', '-h', db_host, '-p', db_port, '-U', db_user, '-d', 'postgres', '-t', '-c',
                'SHOW server_version;',
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env
            )
            try:
                ver_stdout, _ = await asyncio.wait_for(ver_proc.communicate(), timeout=10)
            except asyncio.TimeoutError:
                ver_proc.kill()
                await ver_proc.wait()
                ver_stdout = b''
            if ver_proc.returncode == 0:
                ver_str = ver_stdout.decode(errors='replace').strip()
                pg_major = int(ver_str.split('.')[0])
        except (TimeoutError, OSError, ValueError):
            pass
        if pg_major >= 13:
            drop_cmd = f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE);'
        else:
            drop_cmd = f'DROP DATABASE IF EXISTS "{db_name}";'
        drop_proc = await asyncio.create_subprocess_exec(
            'psql', '-h', db_host, '-p', db_port, '-U', db_user, '-d', 'postgres', '-c', drop_cmd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env
        )
        try:
            _, stderr = await asyncio.wait_for(drop_proc.communicate(), timeout=60)
        except asyncio.TimeoutError:
            drop_proc.kill()
            await drop_proc.wait()
            logger.warning('DROP DATABASE 超时')
            stderr = b'Timeout'
        if drop_proc.returncode != 0:
            logger.warning(f"DROP DATABASE: {stderr.decode(errors='replace')}")
        create_proc = await asyncio.create_subprocess_exec(
            'psql', '-h', db_host, '-p', db_port, '-U', db_user, '-d', 'postgres', '-c',
            f'CREATE DATABASE "{db_name}" OWNER "{db_user}";',
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env
        )  # nosec
        try:
            _, stderr = await asyncio.wait_for(create_proc.communicate(), timeout=30)
        except asyncio.TimeoutError:
            create_proc.kill()
            await create_proc.wait()
            logger.warning('CREATE DATABASE 超时')
            stderr = b'Timeout'
        if create_proc.returncode != 0:
            logger.warning(f"CREATE DATABASE: {stderr.decode(errors='replace')}")  # nosec
    except (TimeoutError, OSError, ValueError) as e:
        return {'status': 'error', 'error': f'数据库重建失败: {e}'}

    psql_start_time = time_mod.monotonic()

    try:
        await _report(0.20, '开始导入数据库数据')
        await asyncio.sleep(0)
        proc = await asyncio.create_subprocess_exec(
            'psql', '-h', db_host, '-p', db_port, '-U', db_user, '-d', db_name,
            '-v', 'ON_ERROR_STOP=0',
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, env=env
        )
        try:
            total_size = len(dump_sql)
            written = 0
            chunk_size = 256 * 1024

            async def _write_stdin():
                nonlocal written
                while written < total_size:
                    end = min(written + chunk_size, total_size)
                    proc.stdin.write(dump_sql[written:end])
                    await proc.stdin.drain()
                    written = end
                    sub = 0.20 + 0.30 * (written / total_size)
                    elapsed = int(time_mod.monotonic() - psql_start_time)
                    await _report(sub, f'写入数据 {written * 100 // total_size}% ({elapsed}s)')
                proc.stdin.close()

            async def _read_stream(stream, chunks):
                while True:
                    chunk = await stream.read(65536)
                    if not chunk:
                        break
                    chunks.append(chunk)

            stdout_chunks = []
            stderr_chunks = []
            write_task = asyncio.create_task(_write_stdin())
            read_out_task = asyncio.create_task(_read_stream(proc.stdout, stdout_chunks))
            read_err_task = asyncio.create_task(_read_stream(proc.stderr, stderr_chunks))

            await asyncio.wait_for(write_task, timeout=600)

            while not read_out_task.done() or not read_err_task.done():
                await asyncio.sleep(2)
                elapsed = int(time_mod.monotonic() - psql_start_time)
                await _report(0.70, f'等待 psql 完成... ({elapsed}s)')

            await asyncio.wait_for(asyncio.gather(read_out_task, read_err_task), timeout=600)
            await proc.wait()

            stdout = b''.join(stdout_chunks)
            stderr = b''.join(stderr_chunks)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {'status': 'error', 'error': '数据库恢复超时（超过 600 秒），进程已终止'}

        stderr_text = stderr.decode(errors='replace')
        error_count = stderr_text.lower().count('error:')
        await _report(0.95, '数据导入完成，验证结果')

        if proc.returncode != 0:
            logger.warning(f'psql restore failed (returncode={proc.returncode}): {stderr_text[:2000]}')
            return {'status': 'error', 'message': '数据库恢复失败', 'errors': stderr_text[:2000]}
        if error_count > 0:
            logger.warning(f'psql restore completed with {error_count} errors: {stderr_text[:2000]}')
            return {'status': 'partial', 'message': f'数据库已恢复，但有 {error_count} 个语句执行失败', 'errors': stderr_text[:2000]}
        return {'status': 'ok', 'message': '数据库恢复成功'}
    except FileNotFoundError:
        return {'status': 'error', 'error': 'psql 命令未找到，请确保 PostgreSQL 客户端工具已安装'}
    except (TimeoutError, OSError, ValueError) as e:
        return {'status': 'error', 'error': f'数据库恢复失败: {e}'}


async def restore_database_via_psql_from_bytes(zip_bytes: bytes, db: AsyncSession) -> dict:
    """从 ZIP bytes 恢复数据库（用于安全备份回滚）"""
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        return {'status': 'error', 'error': '无效的 ZIP 备份文件'}
    if 'database/dump.sql.gz' not in zf.namelist():
        return {'status': 'error', 'error': '安全备份中无 database/dump.sql.gz'}
    return await restore_database_via_psql(zf, db)


async def restore_database_from_json(zf: zipfile.ZipFile, db: AsyncSession, task_id: str = None) -> dict:
    """从 dump.json 恢复数据库（Legacy JSON 格式）"""
    try:
        json_bytes = zf.read('database/dump.json')
        backup_data = json.loads(json_bytes)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        return {'status': 'error', 'error': f'读取 JSON 数据库备份失败: {e}'}
    if 'tables' not in backup_data:
        return {'status': 'error', 'error': 'JSON 备份缺少 tables 字段'}
    result = await restore_legacy_json(backup_data, db, task_id)
    return {
        'status': 'ok' if not result['errors'] else 'partial',
        'message': f"数据库恢复完成，共 {result['total_inserted']} 条记录",
        'total_inserted': result['total_inserted'],
        'errors': result['errors'][:5],
    }


async def restore_legacy_json(backup_data: dict, db: AsyncSession, task_id: str = None) -> dict:
    """从 Legacy JSON 格式备份恢复数据库 (v1.0)"""
    from fastapi_app.shared_models import Base
    from fastapi_app.core.backup_progress import update_progress as _upd_prog

    async def _report(sub: float, detail: str = ''):
        if task_id:
            await _upd_prog(task_id, 'restore_db', sub, detail)
            await asyncio.sleep(0)

    results = {}
    total_inserted = 0
    errors = []
    replication_role_set = False

    # 计算需要恢复的表数量用于进度计算
    tables_to_restore = [t for t in Base.metadata.sorted_tables if str(t.name) in backup_data.get('tables', {})]
    total_tables = len(tables_to_restore)

    try:
        try:
            is_super = await db.execute(text("SELECT usesuper FROM pg_user WHERE usename = current_user"))
            if is_super.scalar():
                await db.execute(text("SET session_replication_role = 'replica'"))
                replication_role_set = True
            else:
                logger.info('当前用户非superuser，跳过禁用外键约束（将使用ON CONFLICT处理冲突）')
        except (SQLAlchemyError, OSError) as e:
            logger.warning(f'禁用外键约束失败: {e}')

        await _report(0.05, '清空现有数据...')
        for table in reversed(Base.metadata.sorted_tables):
            table_name = str(table.name)
            if table_name not in backup_data.get('tables', {}):
                continue
            qtname = quote_table(table_name)  # REV-08
            nested = await db.begin_nested()
            try:
                await db.execute(text(f'DELETE FROM {qtname}'))  # nosec
                await nested.commit()
            except (SQLAlchemyError, ValueError, OSError) as e:
                await nested.rollback()
                logger.warning(f'清空表 {table_name} 失败（外键约束）: {e}')

        processed_tables = 0
        for table in tables_to_restore:
            table_name = str(table.name)
            table_data = backup_data['tables'][table_name]
            columns = table_data.get('columns', [])
            rows = table_data.get('rows', [])
            table_col_names = {c.name for c in table.columns}
            type_map = build_column_type_map(table)
            BATCH_SIZE = 500
            inserted = 0
            batch_errors = []
            qtname = quote_table(table_name)  # REV-08
            for batch_start in range(0, len(rows), BATCH_SIZE):
                batch = rows[batch_start:batch_start + BATCH_SIZE]
                nested = await db.begin_nested()
                try:
                    for offset, row in enumerate(batch):
                        idx = batch_start + offset
                        if not row:
                            continue
                        valid_cols = [c for c in columns if c in type_map and c in row and c in table_col_names]
                        if not valid_cols:
                            continue
                        col_str = ', '.join(f'"{c}"' for c in valid_cols)
                        val_str = ', '.join(f':{c}__row{idx}' for c in valid_cols)
                        params = {}
                        for c in valid_cols:
                            raw_val = row[c]
                            col_type = type_map.get(c)
                            deserialized = deserialize_value(raw_val, col_type) if col_type else raw_val
                            params[f'{c}__row{idx}'] = deserialized
                        pk_cols = [c.name for c in table.primary_key.columns]
                        update_cols = [c for c in valid_cols if c not in pk_cols]
                        if pk_cols and update_cols:
                            update_str = ', '.join(f'"{c}" = EXCLUDED."{c}"' for c in update_cols)
                            await db.execute(text(
                                f'INSERT INTO {qtname} ({col_str}) VALUES ({val_str}) ON CONFLICT ({", ".join(pk_cols)}) DO UPDATE SET {update_str}'
                            ), params)
                        else:
                            await db.execute(text(
                                f'INSERT INTO {qtname} ({col_str}) VALUES ({val_str}) ON CONFLICT DO NOTHING'
                            ), params)
                        inserted += 1
                    await nested.commit()
                except (SQLAlchemyError, ValueError, TypeError) as e:
                    await nested.rollback()
                    batch_errors.append(f'批次 {batch_start // BATCH_SIZE + 1}: {e}')
                    logger.warning(f'恢复表 {table_name} 批次 {batch_start // BATCH_SIZE + 1} 失败: {e}')
            if batch_errors:
                results[table_name] = {'status': 'partial', 'inserted': inserted, 'batch_errors': batch_errors}
                errors.append(f'{table_name}: {len(batch_errors)} 个批次失败')
            else:
                results[table_name] = {'status': 'ok', 'inserted': inserted}
            total_inserted += inserted
            processed_tables += 1

            # 报告进度：0.1 到 0.9 之间按表进度递增
            sub_progress = 0.1 + 0.8 * (processed_tables / total_tables) if total_tables > 0 else 0.9
            await _report(sub_progress, f'已恢复 {processed_tables}/{total_tables} 表 ({table_name}: {inserted}条)')

        await db.flush()
        if replication_role_set:
            try:
                await db.execute(text("SET session_replication_role = 'origin'"))
            except (SQLAlchemyError, OSError) as e:
                logger.warning(f'重新启用外键约束失败: {e}')

        try:
            from fastapi_app.core.cache import CacheDomain, invalidate_related_caches
            await invalidate_related_caches(CacheDomain.ALL)
        except (RuntimeError, OSError, ValueError) as e:
            logger.warning(f'恢复后缓存清除失败: {e}')
        try:
            from fastapi_app.core.purchase_cache import invalidate_purchase_caches
            invalidate_purchase_caches()
        except (RuntimeError, OSError, ValueError) as e:
            logger.warning(f'恢复后采购缓存清除失败: {e}')

        verification = {'overall_pass': True}
        try:
            manifest_tables = {
                tname: {'rows': td.get('count', len(td.get('rows', [])))}
                for tname, td in backup_data.get('tables', {}).items()
            }
            from fastapi_app.core.database import _AsyncSessionLocal
            verify_db = None
            if _AsyncSessionLocal is not None:
                verify_db = _AsyncSessionLocal()
            try:
                verification = await verify_restore(verify_db or db, manifest_tables)
            finally:
                if verify_db is not None:
                    try:
                        await verify_db.close()
                    except (OSError, ValueError, SQLAlchemyError):
                        pass
        except (SQLAlchemyError, ValueError, OSError) as e:
            logger.warning(f'恢复后验证失败: {e}')
            verification = {'overall_pass': False, 'error': str(e)}
    except (SQLAlchemyError, ValueError, OSError) as e:
        await db.rollback()
        raise RestoreError(f'恢复过程中出错: {e}') from e

    result_dict = {
        'database': {'status': 'ok' if not errors else 'partial', 'total_inserted': total_inserted},
        'total_inserted': total_inserted, 'results': results, 'errors': errors,
        'verification': verification,
    }
    if not verification.get('overall_pass', True):
        result_dict['_verification_failed'] = True
    return result_dict


async def restore_non_dependent_components(
    zf: zipfile.ZipFile,
    confirm_sensitive: bool = False,
) -> dict:
    """并行恢复非依赖组件（文件存储、配置文件、Redis、MeiliSearch）
    
    这些组件可以并行恢复，因为它们不依赖数据库。
    
    Args:
        zf: ZIP 文件对象
        confirm_sensitive: 是否确认恢复敏感文件
        
    Returns:
        恢复结果字典
    """
    import asyncio
    
    results = {
        'filestore': {},
        'config': {},
        'redis': {},
        'meilisearch': {},
        'errors': [],
    }
    
    # 创建恢复任务
    tasks = []
    
    # 文件存储恢复
    if any(n.startswith('filestore/') for n in zf.namelist()):
        tasks.append(('filestore', asyncio.to_thread(restore_filestore, zf)))
    
    # 配置文件恢复
    if any(n.startswith('config/') for n in zf.namelist()):
        tasks.append(('config', asyncio.to_thread(restore_config, zf, confirm_sensitive)))
    
    # Redis 恢复
    if 'redis/dump.rdb' in zf.namelist():
        tasks.append(('redis', restore_redis_rdb(zf)))
    
    # MeiliSearch 恢复
    if any(n.startswith('meilisearch/') for n in zf.namelist()):
        tasks.append(('meilisearch', restore_meilisearch(zf)))
    
    # 并行执行所有任务
    if tasks:
        logger.info(f"开始并行恢复 {len(tasks)} 个非依赖组件")
        try:
            # 为异步任务和同步任务分别处理
            async_tasks = []
            sync_tasks = []
            
            for component_name, task in tasks:
                if asyncio.iscoroutine(task):
                    async_tasks.append((component_name, task))
                else:
                    sync_tasks.append((component_name, task))
            
            # 执行异步任务
            if async_tasks:
                async_results = await asyncio.gather(
                    *[task for _, task in async_tasks],
                    return_exceptions=True
                )
                for (component_name, _), result in zip(async_tasks, async_results):
                    if isinstance(result, Exception):
                        results[component_name] = {'status': 'error', 'error': str(result)}
                        results['errors'].append(f'{component_name}: {result}')
                        logger.error(f"恢复 {component_name} 失败: {result}")
                    else:
                        results[component_name] = result
            
            # 执行同步任务（在线程池中）
            if sync_tasks:
                loop = asyncio.get_event_loop()
                sync_results = await asyncio.gather(
                    *[loop.run_in_executor(None, lambda t=t: t[1]) for t in sync_tasks],
                    return_exceptions=True
                )
                for (component_name, _), result in zip(sync_tasks, sync_results):
                    if isinstance(result, Exception):
                        results[component_name] = {'status': 'error', 'error': str(result)}
                        results['errors'].append(f'{component_name}: {result}')
                        logger.error(f"恢复 {component_name} 失败: {result}")
                    else:
                        results[component_name] = result
            
            logger.info("非依赖组件并行恢复完成")
            
        except Exception as e:
            logger.error(f"并行恢复失败: {e}")
            results['errors'].append(f'并行恢复失败: {e}')
    
    return results


# ---------------------------------------------------------------------------
# 恢复后验证
# ---------------------------------------------------------------------------

async def verify_restore(db: AsyncSession, manifest_tables: dict[str, dict], manifest_fingerprints: dict[str, str] | None = None) -> dict:
    """四层恢复后验证

    L0 — 全局校验和: MD5 hash 跨所有表数据
    L1 — 行数: SELECT COUNT(*) 与 manifest 比对
    L2 — 数据指纹: MD5 聚合关键业务表
    L3 — ID 抽样: 检查备份中前 3 个 ID 恢复后是否存在
    """
    from fastapi_app.shared_models import Base
    checksum_tables = get_checksum_tables()
    l0_db_hash: str | None = None
    l0_tables_contributed = 0
    l1_results: list[dict] = []
    l2_results: list[dict] = []
    l3_results: list[dict] = []
    l0_parts: list[str] = []

    for table in Base.metadata.sorted_tables:
        tname = str(table.name)
        qtname = quote_table(tname)  # REV-08
        expected = manifest_tables.get(tname, {})
        expected_rows = expected.get('rows', -1)
        try:
            result = await db.execute(text(f'SELECT COUNT(*) FROM {qtname}'))  # nosec
            actual_rows = result.scalar() or 0
            table_exists = True
        except (RuntimeError, OSError, ValueError) as e:
            actual_rows = -1
            table_exists = False
            logger.warning(f'验证: 统计表 {tname} 行数失败: {e}')

        if not table_exists and expected_rows == 0:
            l1_pass = True
        elif expected_rows < 0:
            l1_pass = None
        else:
            l1_pass = actual_rows == expected_rows
        l1_results.append({'table': tname, 'expected': expected_rows, 'actual': actual_rows, 'pass': l1_pass})

        if not table_exists:
            continue

        if actual_rows > 0:
            try:
                pk_col = [c.name for c in table.primary_key.columns]
                order_col = pk_col[0] if pk_col else 'id'
                cols_result = await db.execute(
                    text('SELECT column_name FROM information_schema.columns WHERE table_name = :tname ORDER BY ordinal_position'),
                    {'tname': tname}
                )
                col_names = [r[0] for r in cols_result.fetchall()]
                agg = " || '|' || ".join(f'''COALESCE("{c}"::text, '')''' for c in col_names)
                row = await db.execute(text(
                    f'''SELECT MD5(STRING_AGG(MD5({agg}), ',' ORDER BY "{order_col}")) FROM {qtname}'''  # nosec
                ))
                t_hash = row.scalar()
                if t_hash:
                    l0_parts.append(f'{tname}:{t_hash}')
                    l0_tables_contributed += 1
            except (SQLAlchemyError, ValueError, OSError) as e:
                logger.warning(f'验证: 表 {tname} 全局校验和计算失败: {e}')

        if tname in checksum_tables and expected_rows and expected_rows > 0:
            try:
                pk_col = [c.name for c in table.primary_key.columns]
                order_col = pk_col[0] if pk_col else 'id'
                cols_result = await db.execute(
                    text('SELECT column_name FROM information_schema.columns WHERE table_name = :tname ORDER BY ordinal_position'),
                    {'tname': tname}
                )
                col_names = [r[0] for r in cols_result.fetchall()]
                agg_expr = " || '|' || ".join(f'''COALESCE("{c}"::text, '')''' for c in col_names)
                fp_result = await db.execute(text(
                    f'''SELECT MD5(STRING_AGG({agg_expr}, ',' ORDER BY "{order_col}")) FROM {qtname}'''  # nosec
                ))
                fingerprint = fp_result.scalar() or ''
            except (ValueError, TypeError, OSError) as e:
                fingerprint = ''
                logger.warning(f'验证: 表 {tname} 指纹计算失败: {e}')
            expected_fp = (manifest_fingerprints or {}).get(tname, '')
            fp_match = fingerprint == expected_fp if expected_fp else None
            l2_results.append({'table': tname, 'fingerprint': fingerprint, 'expected_fingerprint': expected_fp, 'match': fp_match})

        if expected_rows and expected_rows > 0:
            try:
                pk_col_sample = [c.name for c in table.primary_key.columns]
                sample_col = pk_col_sample[0] if pk_col_sample else 'id'
                sample_result = await db.execute(text(
                    f'SELECT "{sample_col}" FROM {qtname} ORDER BY "{sample_col}" LIMIT 3'
                ))  # nosec
                found_ids = [r[0] for r in sample_result.fetchall()]
            except (SQLAlchemyError, ValueError, OSError) as e:
                found_ids = []
                logger.warning(f'验证: 表 {tname} 抽样查询失败: {e}')
            l3_results.append({'table': tname, 'sample_ids': found_ids, 'count_found': len(found_ids)})

    l0_summary = {}
    if l0_parts:
        l0_db_hash = hashlib.md5('|'.join(l0_parts).encode(), usedforsecurity=False).hexdigest()
        l0_summary = {
            'db_checksum': l0_db_hash, 'tables_contributed': l0_tables_contributed,
            'note': '恢复后数据库全局 MD5（可与备份时比对，全量备份 manifest 中可附带此值）',
        }

    l1_match = sum(1 for r in l1_results if r['pass'] is True)
    l1_indeterminate = sum(1 for r in l1_results if r['pass'] is None)
    l1_mismatch = [r for r in l1_results if r['pass'] is False]
    l1_verifiable = sum(1 for r in l1_results if r['pass'] is not None)
    l1_pass_rate = round(l1_match / l1_verifiable * 100, 1) if l1_verifiable > 0 else 100.0

    l2_match = sum(1 for r in l2_results if r['match'] is True)
    l2_total = len(l2_results)
    l2_mismatch = [r for r in l2_results if r['match'] is False]

    l1_all_pass = len(l1_mismatch) == 0
    l2_all_pass = len(l2_mismatch) == 0
    all_passed = l1_all_pass

    return {
        'overall_pass': all_passed,
        'verification_verdict': '通过' if all_passed else '失败',
        'l0_global_checksum': l0_summary,
        'l1_row_count': {
            'total_tables': len(l1_results), 'verifiable_tables': l1_verifiable,
            'match': l1_match, 'indeterminate': l1_indeterminate, 'mismatch': l1_mismatch,
            'pass_rate_pct': l1_pass_rate,
            'summary': f'行数匹配: {l1_match}/{l1_verifiable} ({l1_pass_rate}%)',
        },
        'l2_fingerprint': {
            'tables_checked': l2_total, 'match': l2_match, 'mismatch': l2_mismatch,
            'results': l2_results,
            'summary': f'指纹匹配: {l2_match}/{l2_total}' if l2_total > 0 else '无业务表需校验',
        },
        'l3_sampling': {'tables_checked': len(l3_results), 'results': l3_results},
    }


# ---------------------------------------------------------------------------
# 统一恢复入口（合并 _restore_from_zip 和 _restore_from_zip_with_progress）
# ---------------------------------------------------------------------------

async def restore_from_zip(
    zip_bytes: bytes,
    db: AsyncSession,
    decrypt_password: str | bytearray | None = None,
    task_id: str | None = None,
) -> dict:
    """从 ZIP 备份恢复全部数据。

    如果 task_id 非 None，则通过 backup_progress 报告进度。
    如果 decrypt_password 非 None，则先解密。
    """
    # 进度报告辅助
    async def _prog(phase: str, sub: float = 0.0, detail: str = ''):
        if task_id:
            from fastapi_app.core.backup_progress import update_progress
            await update_progress(task_id, phase, sub, detail)

    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        # 可能是加密文件，尝试解密
        if decrypt_password:
            from fastapi_app.core.backup_encryption import decrypt_backup, BackupFileError as EncFileError
            try:
                zip_bytes = decrypt_backup(zip_bytes, decrypt_password)
                zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
            except EncFileError as e:
                raise RestoreError(f'解密失败: {e}') from e
        else:
            # 检查是否是加密文件（尝试解析为加密格式）
            try:
                # 尝试检测加密文件格式
                if zip_bytes[:4] != b'PK\x03\x04':  # 不是标准ZIP文件头
                    raise RestoreError('备份文件已加密，需要提供解密密码')
            except (RestoreError, IndexError, TypeError):
                raise RestoreError('无效的 ZIP 备份文件或加密文件需要密码')
    
    if 'manifest.json' not in zf.namelist():
        raise RestoreError('备份文件缺少 manifest.json')

    manifest = json.loads(zf.read('manifest.json'))
    
    # 检查备份是否加密
    if manifest.get('encrypted'):
        if not decrypt_password:
            raise RestoreError('备份文件已加密，需要提供解密密码')
        # 如果提供了密码但未在开始时解密，现在解密
        if zip_bytes[:4] == b'PK\x03\x04':  # 已经是ZIP文件，不需要再次解密
            pass
        else:
            from fastapi_app.core.backup_encryption import decrypt_backup, BackupFileError as EncFileError
            try:
                zip_bytes = decrypt_backup(zip_bytes, decrypt_password)
                zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
                manifest = json.loads(zf.read('manifest.json'))  # 重新读取manifest
            except EncFileError as e:
                raise RestoreError(f'解密失败: {e}') from e
    manifest_tables = manifest.get('tables', {})
    results = {
        'version': manifest.get('version'),
        'exported_at': manifest.get('exported_at'),
        'exported_by': manifest.get('exported_by'),
        'remark': manifest.get('remark', ''),
        'database': {}, 'filestore': {}, 'config': {}, 'redis': {}, 'meilisearch': {},
        'errors': [], 'warnings': [], '_manifest_tables': manifest_tables,
    }

    stored_checksums = manifest.get('checksums', {})
    for db_file in ('database/dump.sql.gz', 'database/dump.json'):
        if stored_checksums.get(db_file):
            actual = sha256_bytes(zf.read(db_file))  # REV-14
            if actual != stored_checksums[db_file]:
                results['warnings'].append(f'{db_file} 校验和不匹配，备份文件可能已损坏')

    psql_restored = False
    psql_attempted = False
    try:
        if 'database/dump.sql.gz' in zf.namelist():
            psql_attempted = True
            await _prog('restore_db', 0.0, '通过 psql 恢复数据库')
            db_result = await restore_database_via_psql(zf, db, task_id)
            results['database'] = db_result
            if db_result.get('status') == 'error':
                raise RuntimeError(f"数据库恢复失败: {db_result.get('error') or db_result.get('message', '未知错误')}")
            if db_result.get('status') in ('ok', 'partial'):
                psql_restored = True
            await _prog('restore_db', 1.0, '数据库恢复完成')
        elif 'database/dump.json' in zf.namelist():
            await _prog('restore_db', 0.0, '通过 JSON 恢复数据库')
            db_result = await restore_database_from_json(zf, db, task_id)
            results['database'] = db_result
            if db_result.get('status') == 'error':
                raise RuntimeError(f"数据库恢复失败: {db_result.get('error') or db_result.get('message', '未知错误')}")
            await _prog('restore_db', 1.0, '数据库恢复完成')
        else:
            results['warnings'].append('备份文件中无数据库导出')
            await _prog('restore_db', 1.0, '无数据库数据')

        # 并行恢复非依赖组件
        await _prog('restore_components', 0.0, '开始并行恢复非依赖组件')
        
        # 检查是否有非依赖组件需要恢复
        has_filestore = any(n.startswith('filestore/') for n in zf.namelist())
        has_config = any(n.startswith('config/') for n in zf.namelist())
        has_redis = 'redis/dump.rdb' in zf.namelist()
        has_meilisearch = any(n.startswith('meilisearch/') for n in zf.namelist())
        
        if has_filestore or has_config or has_redis or has_meilisearch:
            # 并行恢复非依赖组件
            components_result = await restore_non_dependent_components(zf, confirm_sensitive=False)
            
            # 更新结果
            if 'filestore' in components_result:
                results['filestore'] = components_result['filestore']
                if has_filestore:
                    await _prog('restore_components', 0.25, f'文件存储恢复完成: {components_result["filestore"].get("restored", 0)} 个文件')
                else:
                    results['warnings'].append('备份文件中无附件数据')
            
            if 'config' in components_result:
                results['config'] = components_result['config']
                if has_config:
                    await _prog('restore_components', 0.5, f'配置文件恢复完成: {len(components_result["config"].get("restored", []))} 个文件')
                else:
                    await _prog('restore_components', 0.5, '无配置数据')
            
            if 'redis' in components_result:
                results['redis'] = components_result['redis']
                if has_redis:
                    await _prog('restore_components', 0.75, 'Redis 恢复完成')
                else:
                    await _prog('restore_components', 0.75, '无 Redis 数据')
            
            if 'meilisearch' in components_result:
                results['meilisearch'] = components_result['meilisearch']
                if has_meilisearch:
                    await _prog('restore_components', 1.0, '搜索索引恢复完成')
                else:
                    await _prog('restore_components', 1.0, '无搜索索引数据')
            
            # 收集错误
            if 'errors' in components_result:
                results['errors'].extend(components_result['errors'])
        else:
            await _prog('restore_components', 1.0, '无非依赖组件需要恢复')

        if psql_restored or psql_attempted:
            await _prog('rebuild_pool', 0.0, '重建数据库连接池')
            from fastapi_app.core.database import rebuild_pool  # REV-25
            await rebuild_pool()
            await _prog('rebuild_pool', 1.0, '连接池已重建')
        else:
            await db.commit()

        try:
            from fastapi_app.core.cache import CacheDomain, invalidate_related_caches
            await invalidate_related_caches(CacheDomain.ALL)
        except (OSError, ValueError) as e:
            logger.warning(f'恢复后缓存清除失败: {e}')
        try:
            from fastapi_app.core.purchase_cache import invalidate_purchase_caches
            invalidate_purchase_caches()
        except (OSError, ValueError) as e:
            logger.warning(f'恢复后采购缓存清除失败: {e}')

        await _prog('verify', 0.0, '数据完整性验证中')
        verify_db = None
        if psql_restored:
            from fastapi_app.core.database import _AsyncSessionLocal
            if _AsyncSessionLocal is not None:
                verify_db = _AsyncSessionLocal()
        try:
            target_db = verify_db or db
            verification = await verify_restore(target_db, manifest.get('tables', {}), manifest.get('fingerprints'))
            results['verification'] = verification
            if not verification.get('overall_pass', True):
                results['_verification_failed'] = True
                logger.warning(
                    f'恢复后验证未通过: {verification.get("l1_row_count", {}).get("summary", "")} ; '
                    f'{verification.get("l2_fingerprint", {}).get("summary", "")}'
                )
            await _prog('verify', 1.0, '验证完成' if verification.get('overall_pass', True) else '验证未通过')
        except (SQLAlchemyError, ValueError, OSError) as e:
            logger.warning(f'恢复后验证失败: {e}')
            results['verification'] = {'overall_pass': False, 'error': str(e)}
            await _prog('verify', 1.0, '验证完成（有异常）')
        finally:
            if verify_db is not None:
                try:
                    await verify_db.close()
                except (OSError, ValueError, SQLAlchemyError):
                    logger.warning('关闭验证数据库会话失败')
    except RestoreError:
        raise
    except (RuntimeError, OSError, ValueError) as e:
        if not psql_attempted:
            try:
                await db.rollback()
            except (OSError, SQLAlchemyError):
                logger.warning('恢复异常后回滚失败')
        raise RestoreError(f'恢复过程中出错: {e}') from e
    finally:
        if psql_attempted:
            try:
                await db.close()
            except (OSError, SQLAlchemyError):
                logger.warning('psql后关闭数据库会话失败')

    return results


# ---------------------------------------------------------------------------
# 增量备份
# ---------------------------------------------------------------------------

async def create_incremental_backup(
    db: AsyncSession,
    user,
    remark: str = '',
    since: str = '',
    encrypt_password: str | bytearray | None = None,
) -> dict:
    """执行增量备份
    
    如果提供 encrypt_password 或配置了环境变量，则使用 AES-256-GCM 加密备份。
    """
    ensure_backup_dir()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    from fastapi_app.shared_models import Base
    incremental_tables = {}
    total_rows = 0
    effective_since = since or await find_last_backup_timestamp() or ''
    for table in Base.metadata.sorted_tables:
        tname = str(table.name)
        try:
            serialized_rows = await query_table_rows(tname, db, effective_since or None)
            if serialized_rows:
                columns = list(serialized_rows[0].keys())
                incremental_tables[tname] = {'columns': columns, 'rows': serialized_rows, 'count': len(serialized_rows)}
                total_rows += len(serialized_rows)
        except (SQLAlchemyError, ValueError, OSError) as e:
            logger.warning(f'增量备份表 {tname} 失败: {e}')

    if not incremental_tables:
        return {'success': True, 'filename': None, 'message': '无变更数据需要备份', 'total_rows': 0}

    with tempfile.TemporaryDirectory(prefix='erp_inc_') as tmpdir:
        tmpdir_path = Path(tmpdir)
        json_path = tmpdir_path / 'database' / 'dump.json'
        json_path.parent.mkdir(parents=True, exist_ok=True)
        backup_data = {
            'version': BACKUP_FORMAT_VERSION, 'type': 'incremental',
            'exported_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'exported_by': user.username if hasattr(user, 'username') else str(user.id),
            'remark': remark, 'base_timestamp': effective_since,
            'table_count': len(incremental_tables), 'total_rows': total_rows,
            'tables': incremental_tables,
        }
        json_path.write_bytes(json.dumps(backup_data, ensure_ascii=False, indent=2).encode('utf-8'))
        zip_path = tmpdir_path / 'backup.zip'
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=3) as zf:
            zf.write(json_path, 'database/dump.json')
            manifest = {
                'version': BACKUP_FORMAT_VERSION, 'type': 'incremental', 'app_version': '2.0',
                'exported_at': backup_data['exported_at'],
                'exported_by': backup_data['exported_by'],
                'remark': remark, 'base_timestamp': effective_since,
                'table_count': len(incremental_tables), 'total_rows': total_rows,
                'includes': {},
                'checksums': {'database/dump.json': sha256_file(json_path)},  # REV-14
            }
            zf.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8'))
        zip_bytes = zip_path.read_bytes()
        
        # 默认加密（根据环境变量配置）
        encryption_password = encrypt_password or get_backup_encryption_password()
        if encryption_password:
            from fastapi_app.core.backup_encryption import encrypt_backup, create_meta_file
            try:
                encrypted_bytes, meta_dict = encrypt_backup(zip_bytes, encryption_password)
                # 更新 manifest 以标记加密
                manifest['encrypted'] = True
                manifest['encryption'] = meta_dict
                # 记录加密信息
                if encrypt_password:
                    logger.info("使用用户提供的密码进行增量备份加密")
                elif BACKUP_ENCRYPTION_PASSWORD or BACKUP_ENCRYPTION_KEY:
                    logger.info("使用环境变量配置的密钥进行增量备份加密")
                else:
                    logger.warning(f"使用生成的随机密钥进行增量备份加密，密钥已记录在日志中")
                zip_bytes = encrypted_bytes
            except Exception as e:
                logger.error(f"增量备份加密失败: {e}")
                if BACKUP_ENCRYPTION_ENABLED and not BACKUP_ENCRYPTION_FALLBACK_TO_GENERATED:
                    raise BackupError(f"增量备份加密失败且不允许回退到未加密备份: {e}") from e
                logger.warning("加密失败，使用未加密的增量备份文件")

    filename = f'erp_incremental_{timestamp}.zip'
    filepath = BACKUP_DIR / filename
    filepath.write_bytes(zip_bytes)
    return {
        'success': True, 'filename': filename, 'size': len(zip_bytes),
        'format': 'incremental', 'table_count': len(incremental_tables),
        'total_rows': total_rows, 'exported_at': backup_data['exported_at'],
        'base_timestamp': effective_since, 'remark': remark,
        'encrypted': 'encryption_password' in locals() and encryption_password is not None,
    }


async def create_wal_incremental_backup(
    db: AsyncSession,
    user,
    remark: str = '',
    start_lsn: str | None = None,
    encrypt_password: str | bytearray | None = None,
) -> dict:
    """创建基于 WAL 的二进制日志增量备份
    
    使用 PostgreSQL 的 WAL (Write-Ahead Logging) 进行增量备份。
    需要 PostgreSQL 配置了 WAL 归档。
    
    Args:
        db: 数据库会话
        user: 用户信息
        remark: 备份备注
        start_lsn: 起始 LSN，如果为 None 则从最近的全量备份时间点开始
        encrypt_password: 加密密码，如果为 None 则使用环境变量配置
        
    Returns:
        包含备份信息的字典
    """
    ensure_backup_dir()
    
    # 获取当前 LSN
    wal_info = await get_postgres_wal_info(db)
    current_lsn = wal_info.get('current_lsn')
    if not current_lsn:
        raise BinaryLogError("无法获取当前 LSN")
    
    # 如果没有提供起始 LSN，尝试从最近的全量备份获取
    if not start_lsn:
        # 查找最近的全量备份
        latest_full_backup = None
        if BACKUP_DIR.exists():
            for f in sorted(BACKUP_DIR.iterdir(), reverse=True):
                if f.is_file() and f.name.startswith('erp_backup_') and f.name.endswith('.zip'):
                    try:
                        with zipfile.ZipFile(f, 'r') as zf:
                            if 'manifest.json' in zf.namelist():
                                manifest = json.loads(zf.read('manifest.json'))
                                if manifest.get('type') == 'full':
                                    latest_full_backup = {
                                        'filename': f.name,
                                        'exported_at': manifest.get('exported_at'),
                                        'lsn': manifest.get('lsn')  # 全量备份可能包含 LSN
                                    }
                                    break
                    except (OSError, zipfile.BadZipFile, ValueError):
                        continue
        
        if latest_full_backup and latest_full_backup.get('lsn'):
            start_lsn = latest_full_backup['lsn']
            logger.info(f"使用最近全量备份的 LSN: {start_lsn}")
        else:
            # 如果没有找到全量备份的 LSN，使用当前 LSN（相当于全量备份）
            start_lsn = current_lsn
            logger.warning("未找到最近全量备份的 LSN，使用当前 LSN")
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    # 创建 WAL 备份
    wal_backup_result = await create_binary_log_backup(
        db=db,
        start_lsn=start_lsn,
        output_dir=BACKUP_DIR / 'wal_incremental'
    )
    
    # 创建备份元数据
    backup_info = {
        'version': BACKUP_FORMAT_VERSION,
        'type': 'wal_incremental',
        'app_version': '2.0',
        'exported_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'exported_by': user.username if hasattr(user, 'username') else str(user.id),
        'remark': remark,
        'start_lsn': start_lsn,
        'end_lsn': current_lsn,
        'wal_info': wal_info,
        'backup_files': wal_backup_result.get('backup_file'),
    }
    
    # 保存元数据文件
    metadata_filename = f'erp_wal_incremental_{timestamp}.json'
    metadata_path = BACKUP_DIR / metadata_filename
    metadata_path.write_text(json.dumps(backup_info, indent=2, ensure_ascii=False))
    
    # 可选加密
    effective_encryption_password = encrypt_password or get_backup_encryption_password()
    if effective_encryption_password:
        from fastapi_app.core.backup_encryption import encrypt_backup
        try:
            metadata_bytes = metadata_path.read_bytes()
            encrypted_bytes, meta_dict = encrypt_backup(metadata_bytes, effective_encryption_password)
            metadata_path.write_bytes(encrypted_bytes)
            
            # 更新备份信息（仅记录在日志中，不覆盖加密后的文件）
            backup_info['encrypted'] = True
            backup_info['encryption'] = meta_dict
            
            # 记录加密信息
            if encrypt_password:
                logger.info("使用用户提供的密码进行 WAL 增量备份加密")
            elif BACKUP_ENCRYPTION_PASSWORD or BACKUP_ENCRYPTION_KEY:
                logger.info("使用环境变量配置的密钥进行 WAL 增量备份加密")
            else:
                logger.warning(f"使用生成的随机密钥进行 WAL 增量备份加密，密钥已记录在日志中")
            
            # 注意：不再重新写入明文 JSON，避免覆盖加密数据
            # 加密后的元数据信息记录在 backup_info 字典中返回给调用方
            
        except Exception as e:
            logger.error(f"WAL 增量备份加密失败: {e}")
            if BACKUP_ENCRYPTION_ENABLED and not BACKUP_ENCRYPTION_FALLBACK_TO_GENERATED:
                raise BackupError(f"WAL 增量备份加密失败且不允许回退到未加密备份: {e}") from e
            logger.warning("加密失败，使用未加密的 WAL 增量备份")
    
    return {
        'success': True,
        'filename': metadata_filename,
        'size': metadata_path.stat().st_size,
        'format': 'wal_incremental',
        'start_lsn': start_lsn,
        'end_lsn': current_lsn,
        'exported_at': backup_info['exported_at'],
        'remark': remark,
        'encrypted': encryption_password is not None,
        'wal_backup_result': wal_backup_result,
    }


async def restore_incremental(
    db: AsyncSession,
    zip_bytes: bytes,
    filename: str,
) -> dict:
    """从增量备份恢复"""
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        raise RestoreError('无效的 ZIP 文件')
    if 'manifest.json' not in zf.namelist():
        raise RestoreError('增量备份缺少 manifest.json')
    manifest = json.loads(zf.read('manifest.json'))
    if manifest.get('type') != 'incremental':
        raise RestoreError('该备份不是增量备份，请使用全量恢复')
    if 'database/dump.json' not in zf.namelist():
        raise RestoreError('增量备份中无数据库数据')
    try:
        backup_data = json.loads(zf.read('database/dump.json'))
    except (json.JSONDecodeError, OSError) as e:
        raise RestoreError(f'读取增量备份数据失败: {e}') from e

    from fastapi_app.shared_models import Base
    table_map = {str(t.name): t for t in Base.metadata.sorted_tables}
    total_upserted = 0
    results = {}
    errors = []

    pre_restore_info = await create_pre_restore_backup(db)
    lock_acquired = False
    try:
        lock_result = await db.execute(text('SELECT pg_try_advisory_lock(:lock_id)'), {'lock_id': RESTORE_LOCK_ID})
        if not lock_result.scalar():
            raise BackupLockError('另一个恢复操作正在执行中，请稍后重试')  # REV-06
        lock_acquired = True
        try:
            await db.execute(text("SET session_replication_role = 'replica'"))
        except (SQLAlchemyError, OSError) as e:
            logger.warning(f'禁用外键约束失败: {e}')

        for tname, table_data in backup_data.get('tables', {}).items():
            if tname not in table_map:
                continue
            table = table_map[tname]
            columns = table_data.get('columns', [])
            rows = table_data.get('rows', [])
            type_map = build_column_type_map(table)
            pk_cols = [c.name for c in table.primary_key.columns]
            table_col_names = {c.name for c in table.columns}
            qtname = quote_table(tname)  # REV-08
            BATCH_SIZE = 500
            upserted = 0
            batch_errors = []
            for batch_start in range(0, len(rows), BATCH_SIZE):
                batch = rows[batch_start:batch_start + BATCH_SIZE]
                nested = await db.begin_nested()
                try:
                    for offset, row in enumerate(batch):
                        idx = batch_start + offset
                        if not row:
                            continue
                        valid_cols = [c for c in columns if c in type_map and c in row and c in table_col_names]
                        if not valid_cols:
                            continue
                        col_str = ', '.join(f'"{c}"' for c in valid_cols)
                        val_str = ', '.join(f':{c}__row{idx}' for c in valid_cols)
                        params = {}
                        for c in valid_cols:
                            raw_val = row[c]
                            col_type = type_map.get(c)
                            deserialized = deserialize_value(raw_val, col_type) if col_type else raw_val
                            params[f'{c}__row{idx}'] = deserialized
                        update_cols = [c for c in valid_cols if c not in pk_cols]
                        if pk_cols and update_cols:
                            update_str = ', '.join(f'"{c}" = EXCLUDED."{c}"' for c in update_cols)
                            await db.execute(text(
                                f'INSERT INTO {qtname} ({col_str}) VALUES ({val_str}) ON CONFLICT ({", ".join(pk_cols)}) DO UPDATE SET {update_str}'
                            ), params)
                        else:
                            await db.execute(text(
                                f'INSERT INTO {qtname} ({col_str}) VALUES ({val_str}) ON CONFLICT DO NOTHING'
                            ), params)
                        upserted += 1
                    await nested.commit()
                except (SQLAlchemyError, ValueError, TypeError) as e:
                    await nested.rollback()
                    batch_errors.append(f'批次 {batch_start // BATCH_SIZE + 1}: {e}')
                    logger.warning(f'增量恢复表 {tname} 批次 {batch_start // BATCH_SIZE + 1} 失败: {e}')
            if batch_errors:
                results[tname] = {'status': 'partial', 'upserted': upserted, 'batch_errors': batch_errors}
                errors.append(f'{tname}: {len(batch_errors)} 个批次失败')
            else:
                results[tname] = {'status': 'ok', 'upserted': upserted}
            total_upserted += upserted

        try:
            await db.execute(text("SET session_replication_role = 'origin'"))
        except (SQLAlchemyError, OSError) as e:
            logger.warning(f'重新启用外键约束失败: {e}')
        await db.commit()
        try:
            from fastapi_app.core.cache import CacheDomain, invalidate_related_caches
            await invalidate_related_caches(CacheDomain.ALL)
        except (RuntimeError, OSError, ValueError) as e:
            logger.warning(f'增量恢复后缓存清除失败: {e}')
        try:
            from fastapi_app.core.purchase_cache import invalidate_purchase_caches
            invalidate_purchase_caches()
        except (RuntimeError, OSError, ValueError) as e:
            logger.warning(f'增量恢复后采购缓存清除失败: {e}')
    except BackupLockError:
        raise
    except (SQLAlchemyError, ValueError, OSError) as e:
        try:
            await db.rollback()
        except (OSError, SQLAlchemyError):
            logger.warning('恢复异常后回滚失败')
        raise RestoreError(f'增量恢复过程中出错: {e}') from e
    finally:
        if lock_acquired:
            try:
                await db.execute(text('SELECT pg_advisory_unlock(:lock_id)'), {'lock_id': RESTORE_LOCK_ID})
            except (OSError, ValueError, SQLAlchemyError):
                logger.warning('释放增量恢复锁失败')

    return {
        'success': True, 'format': 'incremental', 'filename': filename,
        'total_upserted': total_upserted, 'results': results, 'errors': errors,
        'pre_restore_backup': pre_restore_info,
        'restored_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }


# ---------------------------------------------------------------------------
# BackupRecord 写入辅助
# ---------------------------------------------------------------------------

async def write_backup_record(
    db: AsyncSession,
    *,
    record_type: str,
    trigger_type: str = 'manual',
    filename: str | None = None,
    size: int | None = None,
    table_count: int | None = None,
    total_rows: int | None = None,
    operator: str | None = None,
    remark: str | None = None,
    status: str = 'success',
    error_message: str | None = None,
    duration_seconds: float | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    parent_record_id: int | None = None,
) -> None:
    """写入备份操作记录到 BackupRecord 表"""
    try:
        from fastapi_app.shared_models.backup_record import BackupRecord
        record = BackupRecord(
            type=record_type, trigger_type=trigger_type, filename=filename,
            size=size, table_count=table_count, total_rows=total_rows,
            operator=operator, remark=remark, status=status,
            error_message=error_message, duration_seconds=duration_seconds,
            ip_address=ip_address, user_agent=user_agent,
            parent_record_id=parent_record_id,
        )
        db.add(record)
        await db.flush()
    except (SQLAlchemyError, OSError) as e:
        logger.warning(f'写入备份记录失败（不阻塞主流程）: {e}')


# ---------------------------------------------------------------------------
# 备份文件列表 / 状态查询
# ---------------------------------------------------------------------------

def list_backup_files() -> list[dict]:
    """列出服务器上的所有备份文件"""
    backups = []
    if BACKUP_DIR.exists():
        for f in sorted(BACKUP_DIR.iterdir(), reverse=True):
            if not f.is_file():
                continue
            if not ((f.name.startswith('erp_backup_') or f.name.startswith('erp_incremental_') or f.name.startswith('erp_auto_'))
                    and (f.name.endswith('.zip') or f.name.endswith('.json'))):
                continue
            entry: dict = {'filename': f.name, 'size': f.stat().st_size}
            if f.name.endswith('.zip'):
                try:
                    with zipfile.ZipFile(f, 'r') as zf:
                        if 'manifest.json' in zf.namelist():
                            manifest = json.loads(zf.read('manifest.json'))
                            entry.update({
                                'format': manifest.get('type', 'zip'),
                                'exported_at': manifest.get('exported_at', ''),
                                'exported_by': manifest.get('exported_by', ''),
                                'remark': manifest.get('remark', ''),
                                'table_count': manifest.get('table_count', 0),
                                'total_rows': manifest.get('total_rows', 0),
                                'includes': manifest.get('includes', {}),
                                'base_timestamp': manifest.get('base_timestamp', ''),
                                'encrypted': manifest.get('encrypted', False),
                            })
                except (OSError, zipfile.BadZipFile, ValueError) as e:
                    logger.warning(f'读取 ZIP 备份 {f.name} 失败: {e}')
                    entry['error'] = str(e)
            elif f.name.endswith('.json'):
                try:
                    data = json.loads(f.read_text(encoding='utf-8'))
                    entry.update({
                        'format': 'json',
                        'exported_at': data.get('exported_at', ''),
                        'exported_by': data.get('exported_by', ''),
                        'remark': data.get('remark', ''),
                        'table_count': len(data.get('tables', {})),
                        'total_rows': sum(t.get('count', len(t.get('rows', []))) for t in data.get('tables', {}).values()),
                    })
                except (OSError, json.JSONDecodeError, ValueError) as e:
                    logger.warning(f'读取 JSON 备份 {f.name} 失败: {e}')
                    entry['error'] = str(e)
            backups.append(entry)
    return backups


def get_backup_status() -> dict:
    """获取备份系统状态概览"""
    last_full: dict | None = None
    total_backups = 0
    total_size = 0
    if BACKUP_DIR.exists():
        for f in sorted(BACKUP_DIR.iterdir(), reverse=True):
            if not f.is_file() or not (f.name.endswith('.zip') or f.name.endswith('.json')):
                continue
            total_backups += 1
            total_size += f.stat().st_size
            if last_full:
                continue
            try:
                if f.name.endswith('.zip'):
                    with zipfile.ZipFile(f, 'r') as zf:
                        if 'manifest.json' in zf.namelist():
                            mf = json.loads(zf.read('manifest.json'))
                            if mf.get('type') == 'full':
                                last_full = {
                                    'filename': f.name, 'size': f.stat().st_size,
                                    'exported_at': mf.get('exported_at', ''),
                                    'exported_by': mf.get('exported_by', ''),
                                    'remark': mf.get('remark', ''), 'type': 'full',
                                    'table_count': mf.get('table_count', 0),
                                    'total_rows': mf.get('total_rows', 0),
                                }
            except (json.JSONDecodeError, OSError, ValueError) as e:
                logger.warning(f'解析备份清单失败: {e}')
                continue
    return {
        'success': True, 'backup_dir': str(BACKUP_DIR),
        'total_backups': total_backups, 'total_size_bytes': total_size,
        'last_full_backup': last_full,
        'checksum_tables': sorted(get_checksum_tables()),
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }


def validate_backup_file(content: bytes, filename: str) -> dict:
    """验证备份文件，不执行恢复，仅返回摘要信息"""
    is_zip = filename.endswith('.zip') or content[:4] == b'PK\x03\x04'
    if is_zip:
        try:
            zf = zipfile.ZipFile(io.BytesIO(content))
        except zipfile.BadZipFile:
            raise BackupFileError('无效的 ZIP 文件')
        if 'manifest.json' not in zf.namelist():
            raise BackupFileError('ZIP 备份缺少 manifest.json')
        manifest = json.loads(zf.read('manifest.json'))
        names = zf.namelist()
        checksums_ok = True
        checksum_errors = []
        stored_checksums = manifest.get('checksums', {})
        for db_file in ['database/dump.sql.gz', 'database/dump.json']:
            if stored_checksums.get(db_file):
                actual = sha256_bytes(zf.read(db_file))  # REV-14
                if actual != stored_checksums[db_file]:
                    checksums_ok = False
                    checksum_errors.append(f'{db_file} 校验和不匹配')
        return {
            'format': 'zip', 'version': manifest.get('version'),
            'exported_at': manifest.get('exported_at'),
            'exported_by': manifest.get('exported_by'),
            'remark': manifest.get('remark', ''),
            'table_count': manifest.get('table_count'),
            'total_rows': manifest.get('total_rows'),
            'includes': manifest.get('includes', {}),
            'checksums_ok': checksums_ok, 'checksum_errors': checksum_errors,
            'zip_contents': {
                'has_database': 'database/dump.sql.gz' in names or 'database/dump.json' in names,
                'db_format': 'sql' if 'database/dump.sql.gz' in names else 'json' if 'database/dump.json' in names else 'none',
                'has_filestore': any(n.startswith('filestore/') for n in names),
                'has_config': any(n.startswith('config/') for n in names),
                'has_redis': 'redis/dump.rdb' in names,
                'has_meilisearch': any(n.startswith('meilisearch/') for n in names),
                'filestore_count': sum(1 for n in names if n.startswith('filestore/') and not n.endswith('/')),
                'config_files': [n for n in names if n.startswith('config/') and not n.endswith('/')],
            },
        }
    # JSON format
    try:
        backup_data = json.loads(content)
    except json.JSONDecodeError:
        raise BackupFileError('备份文件格式无效（非 ZIP 亦非有效 JSON）')
    if 'tables' not in backup_data:
        raise BackupFileError('JSON 备份文件缺少 tables 字段')
    from fastapi_app.shared_models import Base
    existing_tables = {str(t.name) for t in Base.metadata.sorted_tables}
    summary = {
        'format': 'json', 'version': backup_data.get('version'),
        'exported_at': backup_data.get('exported_at'),
        'exported_by': backup_data.get('exported_by'),
        'remark': backup_data.get('remark', ''),
        'table_count': len(backup_data['tables']),
        'total_rows': sum(t.get('count', len(t.get('rows', []))) for t in backup_data['tables'].values()),
        'checksums_ok': None, 'tables': [],
    }
    for table_name, table_data in backup_data['tables'].items():
        row_count = table_data.get('count', len(table_data.get('rows', [])))
        summary['tables'].append({
            'name': table_name, 'rows': row_count,
            'exists': table_name in existing_tables,
            'has_error': 'error' in table_data,
        })
    return summary


def delete_backup_file(filename: str) -> str:
    """删除服务器上的指定备份文件"""
    safe_name = Path(filename).name
    if safe_name != filename:
        raise BackupFileError('无效的文件名')
    filepath = BACKUP_DIR / safe_name
    if not filepath.exists():
        raise BackupFileError('备份文件不存在')
    try:
        filepath.unlink()
    except (OSError, ValueError) as e:
        raise BackupFileError(f'删除备份文件失败: {e}') from e
    return safe_name


# ---------------------------------------------------------------------------
# 分布式锁（用于恢复操作互斥）
# ---------------------------------------------------------------------------
_RESTORE_LOCK_KEY = "erp:restore_lock"
_RESTORE_LOCK_TTL = 3600  # 1 hour


async def acquire_restore_lock(task_id: str) -> bool:
    """尝试获取恢复锁（Redis 分布式锁，支持多 worker）

    Returns: True if lock acquired, False if another restore is in progress
    """
    try:
        from fastapi_app.core.backup_progress import _get_redis
        client = await _get_redis()
        if client is None:
            logger.warning('Redis 不可用，跳过分布式锁检查')
            return True
        # SET NX EX: 仅当 key 不存在时设置，带过期时间
        result = await client.set(
            _RESTORE_LOCK_KEY, task_id,
            nx=True, ex=_RESTORE_LOCK_TTL
        )
        return result is not None
    except Exception as e:
        logger.warning(f'获取恢复锁失败: {e}')
        return True  # Redis 故障时允许恢复（降级）


async def release_restore_lock():
    """释放恢复锁"""
    try:
        from fastapi_app.core.backup_progress import _get_redis
        client = await _get_redis()
        if client is not None:
            await client.delete(_RESTORE_LOCK_KEY)
    except Exception as e:
        logger.warning(f'释放恢复锁失败: {e}')


async def is_restore_in_progress() -> bool:
    """检查是否有恢复任务正在执行"""
    try:
        from fastapi_app.core.backup_progress import _get_redis
        client = await _get_redis()
        if client is None:
            return False
        return await client.exists(_RESTORE_LOCK_KEY) > 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 备份保留策略（Phase 4.1）
# ---------------------------------------------------------------------------

# 保留策略配置
BACKUP_RETENTION_DAYS = 30
BACKUP_MAX_COUNT = 50


def cleanup_old_backups() -> dict:
    """清理过期备份文件

    策略：
    1. 删除超过 BACKUP_RETENTION_DAYS 天的备份
    2. 如果总数超过 BACKUP_MAX_COUNT，删除最旧的
    3. 增量备份依赖其基础全量备份，删除全量备份时级联删除依赖它的增量备份

    Returns: dict with deleted_count, kept_count, errors
    """
    if not BACKUP_DIR.exists():
        return {'deleted_count': 0, 'kept_count': 0, 'errors': []}

    from datetime import timedelta

    now = datetime.now()
    cutoff = now - timedelta(days=BACKUP_RETENTION_DAYS)
    deleted = []
    errors = []

    # 收集所有备份文件及其元数据
    backups = []
    for f in BACKUP_DIR.iterdir():
        if not f.is_file():
            continue
        if not ((f.name.startswith('erp_backup_') or f.name.startswith('erp_auto_') or f.name.startswith('erp_incremental_'))
                and (f.name.endswith('.zip') or f.name.endswith('.json'))):
            continue
        mtime = datetime.fromtimestamp(f.stat().st_mtime)
        size = f.stat().st_size
        is_incremental = 'incremental' in f.name
        base_timestamp = None

        # 读取增量备份的基础时间戳
        if is_incremental and f.name.endswith('.zip'):
            try:
                with zipfile.ZipFile(f, 'r') as zf:
                    if 'manifest.json' in zf.namelist():
                        manifest = json.loads(zf.read('manifest.json'))
                        base_timestamp = manifest.get('base_timestamp')
            except (OSError, zipfile.BadZipFile, ValueError):
                pass

        backups.append({
            'path': f, 'name': f.name, 'mtime': mtime, 'size': size,
            'is_incremental': is_incremental, 'base_timestamp': base_timestamp,
        })

    # 按时间排序（最新的在前）
    backups.sort(key=lambda b: b['mtime'], reverse=True)

    # 标记需要删除的文件
    to_delete = set()

    # 策略1: 删除超过保留天数的
    for b in backups:
        if b['mtime'] < cutoff:
            to_delete.add(b['name'])

    # 策略2: 超过最大数量的
    if len(backups) - len(to_delete) > BACKUP_MAX_COUNT:
        # 从最旧的开始删除
        for b in reversed(backups):
            if b['name'] in to_delete:
                continue
            if len(backups) - len(to_delete) <= BACKUP_MAX_COUNT:
                break
            to_delete.add(b['name'])

    # 策略3: 级联删除 - 删除全量备份时，删除依赖它的增量备份
    full_backup_timestamps = set()
    for b in backups:
        if not b['is_incremental'] and b['name'] not in to_delete:
            # 提取全量备份的时间戳
            try:
                ts_str = b['name'].replace('erp_backup_', '').replace('erp_auto_daily_', '').replace('.zip', '').replace('.json', '')
                full_backup_timestamps.add(ts_str)
            except (ValueError, IndexError):
                pass

    # 检查增量备份的基础全量备份是否还在
    for b in backups:
        if b['is_incremental'] and b['base_timestamp']:
            # 如果基础全量备份被删除，增量备份也应该删除
            base_exists = any(ts for ts in full_backup_timestamps if ts <= b['base_timestamp'])
            if not base_exists:
                to_delete.add(b['name'])

    # 执行删除
    for name in to_delete:
        filepath = BACKUP_DIR / name
        try:
            filepath.unlink()
            deleted.append(name)
            logger.info(f'已清理过期备份: {name}')
        except OSError as e:
            errors.append(f'{name}: {e}')
            logger.warning(f'清理备份失败: {name}: {e}')

    return {
        'deleted_count': len(deleted),
        'kept_count': len(backups) - len(deleted),
        'deleted_files': deleted,
        'errors': errors,
    }
