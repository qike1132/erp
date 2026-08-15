"""备份服务共享常量与模块级状态。

从原 backup_service.py 提取的常量、路径配置和可变状态，
供 backup 包内所有子模块共享。
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
BACKUP_DIR = Path(os.environ.get('BACKUP_DIR', 'backups/server'))
MAX_BACKUP_FILE_SIZE = 500 * 1024 * 1024
RESTORE_LOCK_ID = 20240426
BACKUP_LOCK_ID = 20240427
BACKUP_OPERATION_TIMEOUT = int(os.environ.get('BACKUP_OPERATION_TIMEOUT', '1800'))
_backup_in_progress: asyncio.Lock = asyncio.Lock()
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
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

# 分布式锁（用于恢复操作互斥）
_RESTORE_LOCK_KEY = "erp:restore_lock"
_RESTORE_LOCK_TTL = 3600  # 1 hour

# 备份保留策略（Phase 4.1）
BACKUP_RETENTION_DAYS = 30
BACKUP_MAX_COUNT = 50
